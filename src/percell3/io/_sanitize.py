"""Name sanitization helpers for IO module."""

from __future__ import annotations

import re

_VALID_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")
_INVALID_CHARS_RE = re.compile(r"[^A-Za-z0-9._-]")


def sanitize_name(value: str, fallback: str = "unnamed") -> str:
    """Sanitize a string for use as a channel/condition/region name.

    Replaces spaces with underscores, strips invalid chars,
    falls back if result is empty.

    Args:
        value: Raw string to sanitize.
        fallback: Value to use if result is empty after cleaning.

    Returns:
        A name matching ``^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$``.
    """
    result = value.strip()
    result = result.replace(" ", "_")
    result = _INVALID_CHARS_RE.sub("", result)

    # Strip leading non-alphanumeric characters
    result = result.lstrip("._-")

    if not result:
        result = fallback

    # Truncate to 255 chars
    result = result[:255]

    return result
