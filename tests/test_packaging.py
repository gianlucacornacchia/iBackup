"""Tests for the Windows packaging step (`packaging/`).

Two kinds of check live here:

* the build *inputs* - the PyInstaller spec, the committed icon and the
  Windows version resource - are validated against the real project metadata,
  so a version bump or a renamed entry point breaks a fast test instead of a
  release build;
* the *smoke test itself* is exercised against real child processes, so the
  one script that decides "did packaging actually work" cannot silently pass
  on a dead artifact.

Building the executable is not done here: PyInstaller needs minutes and a
Windows host. That build plus `packaging/smoke_test.py` run in the `package`
CI job (see `.github/workflows/ci.yml`) and are documented in
`packaging/README.md`.
"""

from __future__ import annotations

import os
import stat
import sys
import tomllib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packaging"))

from smoke_test import main as smoke_test_main  # noqa: E402
from smoke_test import smoke_test_run  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PACKAGING_DIR = ROOT / "packaging"
SPEC_PATH = PACKAGING_DIR / "ibackup.spec"
ICON_PATH = PACKAGING_DIR / "icon.ico"
VERSION_INFO_PATH = PACKAGING_DIR / "version_info.txt"


def project_version() -> str:
    """Return `project.version` from pyproject.toml."""
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return str(tomllib.load(handle)["project"]["version"])


class _SpecCall:
    """Records the keyword arguments a spec passes to a PyInstaller builder."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.args = args
        self.kwargs = kwargs

    def __getattr__(self, name: str) -> object:
        # Real Analysis objects expose attributes (pure, binaries, datas, ...)
        # that the spec forwards to the next builder; hand back a marker so
        # the spec runs unchanged.
        return f"<{name}>"


def run_spec() -> dict[str, _SpecCall]:
    """Execute the spec with stubbed PyInstaller builders.

    Returns the recorded `Analysis`, `PYZ`, `EXE` and `COLLECT` calls. The
    spec is ordinary Python that PyInstaller `exec()`s with `SPECPATH` and the
    builder classes injected, so running it this way is exactly how a build
    consumes it - minus the actual freezing.
    """
    calls: dict[str, _SpecCall] = {}

    def recorder(name: str):
        def record(*args: object, **kwargs: object) -> _SpecCall:
            call = _SpecCall(*args, **kwargs)
            calls[name] = call
            return call

        return record

    namespace: dict[str, object] = {
        "SPECPATH": str(PACKAGING_DIR),
        "DISTPATH": str(ROOT / "dist"),
        "workpath": str(ROOT / "build"),
        "Analysis": recorder("Analysis"),
        "PYZ": recorder("PYZ"),
        "EXE": recorder("EXE"),
        "COLLECT": recorder("COLLECT"),
        "__file__": str(SPEC_PATH),
    }
    exec(compile(SPEC_PATH.read_text(encoding="utf-8"), str(SPEC_PATH), "exec"), namespace)
    return calls


def test_spec_freezes_the_shared_gui_entry_point() -> None:
    analysis = run_spec()["Analysis"]
    scripts = analysis.args[0]
    assert [Path(script).name for script in scripts] == ["run_gui.py"]
    assert Path(scripts[0]).is_file()
    assert str(ROOT / "src") in analysis.kwargs["pathex"]
    # Reached only through iphone_archive.device at runtime.
    assert "pymobiledevice3" in analysis.kwargs["hiddenimports"]


def test_run_gui_shim_calls_the_same_function_as_the_installed_entry_point() -> None:
    """The frozen build must not become a second implementation."""
    with (ROOT / "pyproject.toml").open("rb") as handle:
        entry_point = tomllib.load(handle)["project"]["gui-scripts"]["ibackup-gui"]
    module, _, function = entry_point.partition(":")
    shim = (PACKAGING_DIR / "run_gui.py").read_text(encoding="utf-8")
    assert f"from {module} import {function}" in shim
    assert f"{function}()" in shim


def test_spec_builds_a_windowed_onedir_app_with_icon_and_version_resource() -> None:
    calls = run_spec()
    exe = calls["EXE"]
    assert exe.kwargs["name"] == "ibackup-gui"
    assert exe.kwargs["console"] is False
    assert Path(str(exe.kwargs["icon"])) == ICON_PATH
    assert Path(str(exe.kwargs["version"])) == VERSION_INFO_PATH
    # One-directory build keeps Qt replaceable (LGPL, ADR-0011 item 3).
    assert exe.kwargs["exclude_binaries"] is True
    assert calls["COLLECT"].kwargs["name"] == "ibackup-gui"


def test_committed_icon_is_a_multi_resolution_ico() -> None:
    from make_icon import ICON_SIZES
    from PIL import Image

    assert ICON_PATH.is_file()
    with Image.open(ICON_PATH) as image:
        assert image.format == "ICO"
        available = set(image.info["sizes"])
    assert available == {(size, size) for size in ICON_SIZES}


def read_version_resource() -> tuple[object, dict[str, str]]:
    """Execute `version_info.txt` the way PyInstaller does.

    PyInstaller `exec()`s this file with its version-resource classes in
    scope, so running it with recording stubs both proves the file is still
    valid Python and yields the strings it declares.
    """
    strings: dict[str, str] = {}
    fixed: dict[str, object] = {}

    def string_struct(name: str, value: str) -> tuple[str, str]:
        strings[name] = value
        return name, value

    def fixed_file_info(**kwargs: object) -> dict[str, object]:
        fixed.update(kwargs)
        return fixed

    namespace: dict[str, object] = {
        "VSVersionInfo": lambda **kwargs: kwargs,
        "FixedFileInfo": fixed_file_info,
        "StringFileInfo": lambda tables: tables,
        "StringTable": lambda code, entries: (code, entries),
        "StringStruct": string_struct,
        "VarFileInfo": lambda entries: entries,
        "VarStruct": lambda name, value: (name, value),
    }
    source = VERSION_INFO_PATH.read_text(encoding="utf-8")
    exec(compile(source, str(VERSION_INFO_PATH), "exec"), namespace)
    assert "VSVersionInfo" in source
    return fixed, strings


def test_version_resource_matches_the_project_version() -> None:
    version = project_version()
    fixed, strings = read_version_resource()
    parts = tuple(int(part) for part in version.split("."))
    expected = parts + (0,) * (4 - len(parts))
    assert fixed["filevers"] == expected
    assert fixed["prodvers"] == expected
    assert strings["FileVersion"] == f"{version}.0"
    assert strings["ProductVersion"] == f"{version}.0"
    assert strings["OriginalFilename"] == "ibackup-gui.exe"
    assert strings["InternalName"] == "ibackup-gui"


# The shims below are launched through a small script wrapper, so the payload
# runs as a grandchild that `terminate()` does not reach. Each payload
# therefore exits on its own shortly after the grace period instead of
# sleeping indefinitely, which would hold the captured pipes open.
FAKE_LIFETIME_SECONDS = 4
FAKE_GRACE_SECONDS = 1.0


def _fake_executable(directory: Path, body: str) -> Path:
    """Write a launchable shim that runs `body` with the test interpreter."""
    script = directory / "payload.py"
    script.write_text(body, encoding="utf-8")
    if os.name == "nt":
        launcher = directory / "fake-app.cmd"
        launcher.write_text(f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    else:
        launcher = directory / "fake-app.sh"
        launcher.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8"
        )
        launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR)
    return launcher


def test_smoke_test_fails_when_the_artifact_was_never_built(tmp_path: Path) -> None:
    assert smoke_test_run(tmp_path / "ibackup-gui.exe") == 1


def test_smoke_test_passes_for_a_process_that_keeps_running(tmp_path: Path) -> None:
    app = _fake_executable(tmp_path, f"import time\ntime.sleep({FAKE_LIFETIME_SECONDS})\n")
    assert smoke_test_run(app, grace=FAKE_GRACE_SECONDS) == 0


def test_smoke_test_runs_the_artifact_offscreen(tmp_path: Path) -> None:
    """A frozen GUI must be launchable with no display, as CI has none."""
    marker = tmp_path / "platform.txt"
    app = _fake_executable(
        tmp_path,
        "import os, pathlib, time\n"
        f"pathlib.Path(r'{marker}').write_text(os.environ.get('QT_QPA_PLATFORM', ''))\n"
        f"time.sleep({FAKE_LIFETIME_SECONDS})\n",
    )
    assert smoke_test_run(app, grace=FAKE_GRACE_SECONDS) == 0
    assert marker.read_text() == "offscreen"


def test_smoke_test_fails_when_the_process_exits_immediately(tmp_path: Path) -> None:
    app = _fake_executable(tmp_path, "raise SystemExit(3)\n")
    assert smoke_test_run(app, grace=FAKE_GRACE_SECONDS) == 1


def test_smoke_test_fails_on_a_traceback_from_a_surviving_process(tmp_path: Path) -> None:
    """A missing DLL or import can be logged by a process that stays alive."""
    app = _fake_executable(
        tmp_path,
        "import sys, time, traceback\n"
        "try:\n"
        "    raise ModuleNotFoundError('PySide6')\n"
        "except ModuleNotFoundError:\n"
        "    traceback.print_exc()\n"
        "sys.stderr.flush()\n"
        f"time.sleep({FAKE_LIFETIME_SECONDS})\n",
    )
    assert smoke_test_run(app, grace=FAKE_GRACE_SECONDS) == 1


def test_smoke_test_cli_defaults_to_the_built_artifact_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    assert smoke_test_main([]) == 1
    assert "dist" in capsys.readouterr().err
