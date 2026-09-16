"""Smoke-test a built ``ibackup-gui.exe``.

Launches the frozen executable with an offscreen Qt platform (no display
needed), confirms the process starts and stays alive past a short grace
period instead of crashing on missing DLLs/imports, then terminates it
cleanly and inspects its stderr for an unhandled traceback. This is a real
process launch of the actual artifact, not a check of the Python source, so
it is the check that answers "did packaging actually work" - not "surely the
spec looks right".

Usage after a build (see packaging/README.md):

    .venv\\Scripts\\python packaging\\smoke_test.py dist\\ibackup-gui\\ibackup-gui.exe
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

STARTUP_GRACE_SECONDS = 5.0
SHUTDOWN_TIMEOUT_SECONDS = 10.0
_CRASH_MARKERS = ("Traceback (most recent call last)", "ModuleNotFoundError", "ImportError")


def smoke_test_run(exe_path: Path, grace: float = STARTUP_GRACE_SECONDS) -> int:
    """Launch, watch and cleanly stop the built executable.

    exe_path: path to the frozen ``ibackup-gui.exe``.
    grace: seconds the process must stay alive to count as "started".
    Returns 0 on a clean start, 1 on a missing artifact, early exit or a
    traceback in stderr.
    """
    if not exe_path.is_file():
        print(f"Built artifact not found: {exe_path}", file=sys.stderr)
        return 1

    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    process = subprocess.Popen(
        [str(exe_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    time.sleep(grace)
    started_ok = process.poll() is None
    if started_ok:
        process.terminate()
    try:
        stdout, stderr = process.communicate(timeout=SHUTDOWN_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
    stderr_text = stderr.decode(errors="replace")

    if not started_ok:
        print(
            f"{exe_path} exited before the {grace:.1f}s grace period elapsed "
            f"(exit code {process.returncode}):",
            file=sys.stderr,
        )
        print(stderr_text, file=sys.stderr)
        return 1
    if any(marker in stderr_text for marker in _CRASH_MARKERS):
        print(f"{exe_path} logged a crash while running:", file=sys.stderr)
        print(stderr_text, file=sys.stderr)
        return 1

    print(
        f"OK: {exe_path} started and ran for {grace:.1f}s under "
        "QT_QPA_PLATFORM=offscreen without crashing."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "exe",
        nargs="?",
        type=Path,
        default=Path("dist/ibackup-gui/ibackup-gui.exe"),
        help="path to the built executable (default: dist/ibackup-gui/ibackup-gui.exe)",
    )
    parser.add_argument(
        "--grace",
        type=float,
        default=STARTUP_GRACE_SECONDS,
        help="seconds the process must stay alive to count as started",
    )
    args = parser.parse_args(argv)
    return smoke_test_run(args.exe, args.grace)


if __name__ == "__main__":
    raise SystemExit(main())
