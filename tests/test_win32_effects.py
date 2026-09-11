"""Mocked native-call coverage, not evidence of Windows rendering."""

from __future__ import annotations

import ctypes
import sys
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from iphone_archive.gui import win32_effects as effects


@pytest.fixture
def native_calls(monkeypatch):
    """Substitute the Windows platform and collect DWM attribute requests."""
    calls = []
    monkeypatch.setattr(
        effects,
        "sys",
        SimpleNamespace(platform="win32", getwindowsversion=lambda: SimpleNamespace(build=22621)),
    )
    monkeypatch.setattr(
        effects,
        "win32_effects_set_attribute",
        lambda hwnd, attribute, value: calls.append((hwnd, attribute, value)) or 0,
    )
    monkeypatch.setattr(effects, "win32_effects_extend_frame", lambda hwnd: 0)
    return calls


def test_no_dll_calls_off_windows(monkeypatch):
    monkeypatch.setattr(effects, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(
        effects,
        "win32_effects_set_attribute",
        lambda *args: pytest.fail("Windows call off Windows"),
    )
    assert effects.win32_effects_appearance() == effects.WindowsAppearance()
    assert (
        effects.win32_effects_apply(1, True, effects.WindowsAppearance()) == effects.WindowEffects()
    )


@pytest.mark.parametrize(
    "build,attributes",
    [(19045, []), (21999, []), (22000, [20, 33]), (22620, [20, 33]), (22621, [20, 33, 38])],
)
def test_build_guards_each_attribute(native_calls, build, attributes, caplog):
    with caplog.at_level("INFO"):
        effects.win32_effects_apply(123, True, effects.WindowsAppearance(build=build))
    assert [item[1] for item in native_calls] == attributes
    if build < 22621:
        assert "unsupported" in caplog.text


def test_normal_launch_keeps_solid_background_until_probe_validated(native_calls):
    result = effects.win32_effects_apply(
        123, True, effects.WindowsAppearance(build=22621, transparency=True)
    )
    assert native_calls == [(123, 20, 1), (123, 33, 2), (123, 38, 1)]
    assert result == effects.WindowEffects(True, True, False)


def test_opt_in_mica_probe_preserves_native_chrome(native_calls):
    result = effects.win32_effects_apply(
        123, True, effects.WindowsAppearance(build=22621, transparency=True), mica_probe=True
    )
    assert native_calls == [(123, 20, 1), (123, 33, 2), (123, 38, 2)]
    assert result.mica_requested


@pytest.mark.parametrize("contrast,transparency", [(True, True), (False, False), (True, False)])
def test_accessibility_and_transparency_disable_mica(native_calls, contrast, transparency):
    result = effects.win32_effects_apply(
        123,
        True,
        effects.WindowsAppearance(build=22621, high_contrast=contrast, transparency=transparency),
        mica_probe=True,
    )
    assert not result.mica_requested
    assert (123, 38, 1) in native_calls
    assert (123, 20, int(not contrast)) in native_calls


@pytest.mark.parametrize("hresult", [-2147024809, 0x80070057])
def test_hresult_failure_is_logged_and_returns_solid(native_calls, monkeypatch, caplog, hresult):
    monkeypatch.setattr(effects, "win32_effects_set_attribute", lambda *args: hresult)
    result = effects.win32_effects_apply(
        123, True, effects.WindowsAppearance(build=22621, transparency=True), mica_probe=True
    )
    assert result == effects.WindowEffects()
    assert "HRESULT 0x80070057" in caplog.text
    assert "solid fallback" in caplog.text


@pytest.mark.parametrize("error", [OSError("DLL missing"), AttributeError("export missing")])
def test_native_load_failure_is_observable(native_calls, monkeypatch, caplog, error):
    def fail(*args):
        raise error

    monkeypatch.setattr(effects, "win32_effects_set_attribute", fail)
    assert not effects.win32_effects_apply(
        123, True, effects.WindowsAppearance(build=22621)
    ).mica_requested
    assert str(error) in caplog.text


def test_frame_failure_reverts_backdrop(native_calls, monkeypatch, caplog):
    monkeypatch.setattr(effects, "win32_effects_extend_frame", lambda hwnd: 0x80004005)
    result = effects.win32_effects_apply(
        123, True, effects.WindowsAppearance(build=22621, transparency=True), mica_probe=True
    )
    assert not result.mica_requested
    assert native_calls[-1] == (123, 38, 1)
    assert "frame extension failed" in caplog.text


def test_frame_load_failure_reverts_backdrop(native_calls, monkeypatch, caplog):
    def fail(hwnd):
        raise OSError("frame unavailable")

    monkeypatch.setattr(effects, "win32_effects_extend_frame", fail)
    result = effects.win32_effects_apply(
        123, False, effects.WindowsAppearance(build=22621, transparency=True), mica_probe=True
    )
    assert not result.mica_requested
    assert native_calls[-1] == (123, 38, 1)
    assert "frame unavailable" in caplog.text


def test_invalid_hwnd_is_not_silently_accepted(native_calls):
    with pytest.raises(ValueError, match="handle"):
        effects.win32_effects_apply(0, False, effects.WindowsAppearance(build=22621))


def test_windows_appearance_reads_preferences(native_calls, monkeypatch):
    values = {"AppsUseLightTheme": 0, "EnableTransparency": 1, "AccentColor": 0xFFCC6633}
    monkeypatch.setattr(effects, "win32_effects_registry_value", lambda path, name: values[name])
    monkeypatch.setattr(effects, "win32_effects_high_contrast", lambda: False)
    assert effects.win32_effects_appearance() == effects.WindowsAppearance(
        build=22621, dark=True, accent=0xFFCC6633, transparency=True
    )


def test_unknown_accessibility_preserves_native_colors(native_calls, monkeypatch, caplog):
    monkeypatch.setattr(effects, "win32_effects_registry_value", lambda *args: None)

    def fail():
        raise OSError("access denied")

    monkeypatch.setattr(effects, "win32_effects_high_contrast", fail)
    result = effects.win32_effects_appearance()
    assert result.high_contrast
    assert not result.transparency
    assert result.dark is None
    assert "preserving native colors" in caplog.text


def test_ctypes_hwnd_is_pointer_sized_and_attributes_are_32_bit(monkeypatch):
    monkeypatch.setattr(effects, "sys", SimpleNamespace(platform="win32"))
    received = []

    def native(hwnd, attribute, value, size):
        received.append(
            (
                hwnd,
                attribute,
                ctypes.cast(value, ctypes.POINTER(ctypes.c_int32)).contents.value,
                size,
            )
        )
        return 0

    monkeypatch.setattr(
        ctypes,
        "WinDLL",
        lambda *args, **kwargs: SimpleNamespace(DwmSetWindowAttribute=native),
        raising=False,
    )
    handle = 0x123456789ABC
    assert effects.win32_effects_set_attribute(handle, 38, 2) == 0
    assert received == [(handle, 38, 2, 4)]
    assert native.argtypes[0] is ctypes.c_void_p
    assert ctypes.sizeof(native.restype) == 4


@pytest.mark.parametrize("enabled", [False, True])
def test_high_contrast_native_layout(monkeypatch, enabled):
    monkeypatch.setattr(effects, "sys", SimpleNamespace(platform="win32"))

    def native(action, size, pointer, flags):
        assert action == 0x0042
        assert size == ctypes.sizeof(effects.HighContrast)
        assert flags == 0
        contrast = ctypes.cast(pointer, ctypes.POINTER(effects.HighContrast)).contents
        assert contrast.size == size
        contrast.flags = int(enabled)
        return 1

    monkeypatch.setattr(
        ctypes,
        "WinDLL",
        lambda *args, **kwargs: SimpleNamespace(SystemParametersInfoW=native),
        raising=False,
    )
    assert effects.win32_effects_high_contrast() is enabled


def test_frame_extension_uses_four_signed_margins(monkeypatch):
    monkeypatch.setattr(effects, "sys", SimpleNamespace(platform="win32"))

    def native(hwnd, pointer):
        assert hwnd == 123
        margins = ctypes.cast(pointer, ctypes.POINTER(ctypes.c_int32 * 4)).contents
        assert list(margins) == [-1, -1, -1, -1]
        return 0

    monkeypatch.setattr(
        ctypes,
        "WinDLL",
        lambda *args, **kwargs: SimpleNamespace(DwmExtendFrameIntoClientArea=native),
        raising=False,
    )
    assert effects.win32_effects_extend_frame(123) == 0


@pytest.mark.parametrize("value,kind,expected", [(1, 4, 1), ("1", 1, None), ("1", 4, None)])
def test_registry_accepts_only_dword_values(monkeypatch, value, kind, expected, caplog):
    monkeypatch.setattr(effects, "sys", SimpleNamespace(platform="win32"))
    registry = SimpleNamespace(
        HKEY_CURRENT_USER=123,
        REG_DWORD=4,
        OpenKey=lambda *args: nullcontext(object()),
        QueryValueEx=lambda *args: (value, kind),
    )
    monkeypatch.setitem(sys.modules, "winreg", registry)
    assert effects.win32_effects_registry_value("path", "name") == expected
    if expected is None:
        assert "not a DWORD" in caplog.text


def test_missing_registry_preference_is_logged(monkeypatch, caplog):
    monkeypatch.setattr(effects, "sys", SimpleNamespace(platform="win32"))

    def fail(*args):
        raise FileNotFoundError("not configured")

    monkeypatch.setitem(sys.modules, "winreg", SimpleNamespace(HKEY_CURRENT_USER=123, OpenKey=fail))
    with caplog.at_level("DEBUG", logger=effects.LOGGER.name):
        assert effects.win32_effects_registry_value("path", "name") is None
    assert "not configured" in caplog.text


@pytest.mark.parametrize(
    "function,args",
    [
        (effects.win32_effects_high_contrast, ()),
        (effects.win32_effects_registry_value, ("path", "name")),
        (effects.win32_effects_set_attribute, (123, 38, 2)),
        (effects.win32_effects_extend_frame, (123,)),
    ],
)
def test_native_primitives_reject_off_windows(monkeypatch, function, args):
    monkeypatch.setattr(effects, "sys", SimpleNamespace(platform="linux"))
    with pytest.raises(OSError, match="require"):
        function(*args)
