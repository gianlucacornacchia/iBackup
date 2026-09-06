"""Windows/cross-platform-safe album and file naming.

Produces names that are valid on Windows (NTFS/exFAT) file systems: no reserved
characters or device names, no trailing dots/spaces, bounded length, and stable
resolution of case-insensitive collisions. Symbolic links are never used by the
archive, so every sanitized name must be usable as a real on-disk file name.
"""

from __future__ import annotations

import hashlib

# Characters forbidden in Windows path components.
RESERVED_CHARS = set('<>:"/\\|?*')

# Reserved Windows device names (case-insensitive), without extension.
RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{digit}" for digit in range(1, 10)),
    *(f"lpt{digit}" for digit in range(1, 10)),
}

# Conservative per-component length limit keeping total paths under the legacy
# Windows 260-character limit with room for the archive root and separators.
MAX_COMPONENT_LENGTH = 120

REPLACEMENT_CHAR = "_"


def name_safety_sanitize_component(raw_name: str, fallback: str = "unnamed") -> str:
    """Sanitize a single path component into a Windows-safe name.

    raw_name: the original album or file-stem text to sanitize.
    fallback: name used when sanitization would otherwise yield an empty string.
    Returns a non-empty, Windows-safe path component (no extension handling).
    """
    cleaned_chars = []
    for char in raw_name:
        if char in RESERVED_CHARS or ord(char) < 32:
            cleaned_chars.append(REPLACEMENT_CHAR)
        else:
            cleaned_chars.append(char)
    collapsed = "".join(cleaned_chars).strip().rstrip(". ")
    if not collapsed:
        collapsed = fallback
    if collapsed.split(".")[0].lower() in RESERVED_NAMES:
        collapsed = f"{collapsed}{REPLACEMENT_CHAR}"
    result = name_safety_limit_length(collapsed)
    return result


def name_safety_limit_length(name: str, max_length: int = MAX_COMPONENT_LENGTH) -> str:
    """Trim a name to a maximum length while keeping it deterministic.

    name: the candidate name to bound.
    max_length: maximum number of characters allowed.
    Returns the name unchanged when short enough, otherwise a truncated form
    with a short content hash suffix to preserve uniqueness.
    """
    if len(name) <= max_length:
        result = name
    else:
        digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:8]
        keep = max_length - len(digest) - 1
        result = f"{name[:keep]}-{digest}"
    return result


def name_safety_split_extension(file_name: str) -> tuple[str, str]:
    """Split a file name into a stem and a lowercase extension.

    file_name: the original file name (may contain multiple dots).
    Returns a tuple (stem, extension) where extension includes the leading dot
    or is empty when there is none.
    """
    dot_index = file_name.rfind(".")
    if dot_index <= 0:
        result = (file_name, "")
    else:
        result = (file_name[:dot_index], file_name[dot_index:].lower())
    return result


def name_safety_safe_file_name(file_name: str, fallback: str = "file") -> str:
    """Sanitize a full file name, preserving its extension.

    file_name: the original file name including extension.
    fallback: stem used when the sanitized stem would be empty.
    Returns a Windows-safe file name with a sanitized stem and lowercase
    extension.
    """
    stem, extension = name_safety_split_extension(file_name)
    safe_stem = name_safety_sanitize_component(stem, fallback=fallback)
    safe_extension = name_safety_sanitize_component(extension.lstrip("."), fallback="")
    if safe_extension and safe_extension != "_":
        result = f"{safe_stem}.{safe_extension}"
    else:
        result = safe_stem
    return result


def name_safety_resolve_collision(candidate: str, taken_lower: set[str]) -> str:
    """Return a name that does not collide case-insensitively with existing ones.

    candidate: the desired (already sanitized) name.
    taken_lower: set of already-used names in lowercase form.
    Returns candidate when free, otherwise a suffixed variant guaranteed unique
    against taken_lower.
    """
    if candidate.lower() not in taken_lower:
        result = candidate
    else:
        stem, extension = name_safety_split_extension(candidate)
        counter = 1
        result = candidate
        while result.lower() in taken_lower:
            result = f"{stem}-{counter}{extension}"
            counter += 1
    return result
