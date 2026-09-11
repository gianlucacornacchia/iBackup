"""Build-guarded Windows appearance queries and observable DWM requests.

No Qt imports or DLL loading at import time. A successful DWM request is not
evidence that Mica is visible through Qt's client painting.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from dataclasses import dataclass

LOGGER = logging.getLogger(__name__)

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_SYSTEMBACKDROP_TYPE = 38
WINDOWS_11_BUILD = 22000
MICA_MINIMUM_BUILD = 22621


@dataclass(frozen=True)
class WindowsAppearance:
    """System preferences; unknown accessibility state selects native rendering."""

    build: int = 0
    dark: bool | None = None
    accent: int | None = None
    high_contrast: bool = False
    transparency: bool = False


@dataclass(frozen=True)
class WindowEffects:
    """Accepted requests, not a claim about the rendered Windows appearance."""

    dark_caption: bool = False
    rounded_corners: bool = False
    mica_requested: bool = False


class HighContrast(ctypes.Structure):
    """Win32 HIGHCONTRASTW layout; field names follow the ctypes ABI."""

    _fields_ = [
        ("size", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("scheme", ctypes.c_wchar_p),
    ]


def win32_effects_high_contrast() -> bool:
    """Query SPI_GETHIGHCONTRAST; raise OSError if Windows cannot answer."""
    if sys.platform != "win32":
        raise OSError("High-contrast query requires Windows")
    contrast = HighContrast()
    contrast.size = ctypes.sizeof(contrast)
    function = ctypes.WinDLL("user32", use_last_error=True).SystemParametersInfoW
    function.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32]
    function.restype = ctypes.c_int32
    if not function(0x0042, contrast.size, ctypes.byref(contrast), 0):
        raise ctypes.WinError(ctypes.get_last_error())
    return bool(contrast.flags & 0x00000001)


def win32_effects_registry_value(path: str, name: str) -> int | None:
    """Read a per-user DWORD; log missing/unreadable values and return None."""
    if sys.platform != "win32":
        raise OSError("Registry query requires Windows")
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as registry_key:
            value, kind = winreg.QueryValueEx(registry_key, name)
    except OSError as error:
        LOGGER.debug("Windows preference %s\\%s unavailable: %s", path, name, error)
        return None
    if kind != winreg.REG_DWORD or not isinstance(value, int):
        LOGGER.warning("Windows preference %s\\%s is not a DWORD", path, name)
        return None
    return value


def win32_effects_appearance() -> WindowsAppearance:
    """Read Windows theme/accent/accessibility preferences, or neutral off Windows."""
    if sys.platform != "win32":
        return WindowsAppearance()
    personalize = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
    light = win32_effects_registry_value(personalize, "AppsUseLightTheme")
    transparency = win32_effects_registry_value(personalize, "EnableTransparency")
    accent = win32_effects_registry_value(r"Software\Microsoft\Windows\DWM", "AccentColor")
    try:
        high_contrast = win32_effects_high_contrast()
    except (OSError, AttributeError) as error:
        LOGGER.warning("High-contrast query failed: %s; preserving native colors", error)
        high_contrast = True
    return WindowsAppearance(
        build=sys.getwindowsversion().build,
        dark=None if light is None else light == 0,
        accent=accent,
        high_contrast=high_contrast,
        transparency=transparency == 1,
    )


def win32_effects_set_attribute(hwnd: int, attribute: int, value: int) -> int:
    """Call DwmSetWindowAttribute with pointer-sized HWND and 32-bit values/HRESULT."""
    if sys.platform != "win32":
        raise OSError("DWM attributes require Windows")
    function = ctypes.WinDLL("dwmapi", use_last_error=True).DwmSetWindowAttribute
    function.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32]
    function.restype = ctypes.c_int32
    setting = ctypes.c_int32(value)
    return int(function(hwnd, attribute, ctypes.byref(setting), ctypes.sizeof(setting)))


def win32_effects_extend_frame(hwnd: int) -> int:
    """Extend glass through the client area for the opt-in Windows Mica probe."""
    if sys.platform != "win32":
        raise OSError("DWM frame extension requires Windows")
    function = ctypes.WinDLL("dwmapi", use_last_error=True).DwmExtendFrameIntoClientArea
    function.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    function.restype = ctypes.c_int32
    margins = (ctypes.c_int32 * 4)(-1, -1, -1, -1)
    return int(function(hwnd, ctypes.byref(margins)))


def win32_effects_request(hwnd: int, attribute: int, value: int, build: int) -> bool:
    """Request a supported DWM attribute, logging unsupported attributes and failures."""
    minimum = MICA_MINIMUM_BUILD if attribute == DWMWA_SYSTEMBACKDROP_TYPE else WINDOWS_11_BUILD
    if build < minimum:
        LOGGER.info(
            "DWM attribute %s unsupported on build %s; using solid/native fallback",
            attribute,
            build,
        )
        return False
    try:
        result = win32_effects_set_attribute(hwnd, attribute, value)
    except (OSError, AttributeError) as error:
        LOGGER.warning("DWM attribute %s failed: %s; using solid fallback", attribute, error)
        return False
    if result & 0x80000000:
        LOGGER.warning(
            "DWM attribute %s failed: HRESULT 0x%08X; using solid fallback",
            attribute,
            result & 0xFFFFFFFF,
        )
        return False
    return True


def win32_effects_apply(
    hwnd: int, dark: bool, appearance: WindowsAppearance, *, mica_probe: bool = False
) -> WindowEffects:
    """Apply guarded native chrome; Mica client transparency is explicitly experimental.

    hwnd: native top-level window handle.
    dark: resolved application theme.
    appearance: current system build and accessibility/transparency preferences.
    mica_probe: opt in to the unverified glass client painting experiment.
    Returns accepted effect requests. Unsupported/failed requests keep solid Qt painting.
    """
    if sys.platform != "win32":
        LOGGER.debug("DWM unavailable on %s; using solid background", sys.platform)
        return WindowEffects()
    if hwnd <= 0:
        raise ValueError("DWM requires a valid window handle")
    caption = win32_effects_request(
        hwnd,
        DWMWA_USE_IMMERSIVE_DARK_MODE,
        int(dark and not appearance.high_contrast),
        appearance.build,
    )
    rounded = win32_effects_request(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, 2, appearance.build)
    enable_mica = mica_probe and appearance.transparency and not appearance.high_contrast
    backdrop = win32_effects_request(
        hwnd, DWMWA_SYSTEMBACKDROP_TYPE, 2 if enable_mica else 1, appearance.build
    )
    if enable_mica and backdrop:
        try:
            result = win32_effects_extend_frame(hwnd)
        except (OSError, AttributeError) as error:
            LOGGER.warning("DWM frame extension failed: %s; using solid fallback", error)
        else:
            if not result & 0x80000000:
                LOGGER.info("Mica probe requests accepted; visual Windows validation required")
                return WindowEffects(caption, rounded, True)
            LOGGER.warning(
                "DWM frame extension failed: HRESULT 0x%08X; using solid fallback",
                result & 0xFFFFFFFF,
            )
        win32_effects_request(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, 1, appearance.build)
    else:
        LOGGER.info(
            "Using solid background (Mica probe=%s, transparency=%s, high contrast=%s)",
            mica_probe,
            appearance.transparency,
            appearance.high_contrast,
        )
    return WindowEffects(caption, rounded)
