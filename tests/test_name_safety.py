"""Tests for Windows-safe naming, including property-based invariants."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from iphone_archive.core import name_safety


def test_reserved_chars_replaced():
    """Reserved characters are replaced, not kept."""
    result = name_safety.name_safety_sanitize_component('a<b>c:d"e/f\\g|h?i*j')
    for char in '<>:"/\\|?*':
        assert char not in result


def test_reserved_device_name_disambiguated():
    """Reserved device names get a suffix so they are usable on Windows."""
    assert name_safety.name_safety_sanitize_component("CON").lower() != "con"
    assert name_safety.name_safety_sanitize_component("nul").lower() != "nul"


def test_trailing_dot_and_space_stripped():
    """Trailing dots and spaces are removed."""
    result = name_safety.name_safety_sanitize_component("Vacation.  ")
    assert not result.endswith(".")
    assert not result.endswith(" ")


def test_empty_falls_back():
    """An all-invalid input yields the fallback, never empty."""
    assert name_safety.name_safety_sanitize_component("   ", fallback="album") == "album"


def test_safe_name_preserved():
    """An already-safe name is returned unchanged."""
    assert name_safety.name_safety_sanitize_component("Family Trip 2024") == "Family Trip 2024"


def test_file_name_keeps_extension():
    """File-name sanitization keeps a lowercase extension."""
    assert name_safety.name_safety_safe_file_name("IMG_0001.HEIC") == "IMG_0001.heic"


def test_collision_resolution_unique():
    """Collision resolution returns a name not already taken."""
    taken = {"img.heic", "img-1.heic"}
    result = name_safety.name_safety_resolve_collision("IMG.heic", taken)
    assert result.lower() not in taken


@given(raw=st.text(max_size=300))
def test_sanitized_is_always_windows_safe(raw):
    """Property: output has no reserved chars/names, no trailing dot/space, bounded length."""
    result = name_safety.name_safety_sanitize_component(raw, fallback="unnamed")
    assert result
    assert len(result) <= name_safety.MAX_COMPONENT_LENGTH
    assert not (set(result) & name_safety.RESERVED_CHARS)
    assert not result.endswith(".")
    assert not result.endswith(" ")
    assert result.split(".")[0].lower() not in name_safety.RESERVED_NAMES


@given(raw=st.text(max_size=300))
def test_sanitize_is_idempotent(raw):
    """Property: sanitizing an already-sanitized name changes nothing."""
    once = name_safety.name_safety_sanitize_component(raw, fallback="unnamed")
    twice = name_safety.name_safety_sanitize_component(once, fallback="unnamed")
    assert once == twice
