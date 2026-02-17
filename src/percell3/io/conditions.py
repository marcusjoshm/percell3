"""Condition auto-detection from FOV names."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Suffix patterns that typically identify site/field-of-view within a condition.
# Tried in order; first pattern where ALL FOVs match wins.
_SUFFIX_PATTERNS = [
    r"_s\d+$",
    r"_\d+$",
    r"_fov\d+$",
    r"_field\d+$",
    r"_site\d+$",
]


@dataclass(frozen=True)
class ConditionDetectionResult:
    """Result of automatic condition detection from FOV names.

    Attributes:
        condition_map: Maps original FOV token to its detected condition name.
        fov_name_map: Maps original FOV token to a cleaned site/FOV name.
        conditions: Unique condition names, sorted alphabetically.
        pattern_used: The suffix regex pattern that matched (for display).
    """

    condition_map: dict[str, str]
    fov_name_map: dict[str, str]
    conditions: list[str]
    pattern_used: str


def detect_conditions(fovs: list[str]) -> ConditionDetectionResult | None:
    """Analyze FOV names to detect condition groupings.

    Heuristic:
    1. Try each suffix pattern (e.g. ``_s\\d+$``, ``_\\d+$``).
    2. If ALL FOV names match a pattern AND have multiple distinct
       prefixes, conditions are detected.
    3. Returns None if no pattern matches or only one prefix found.

    Args:
        fovs: List of FOV name strings (e.g. from ScanResult.fovs).

    Returns:
        A ConditionDetectionResult if conditions were detected, else None.
    """
    if not fovs:
        return None

    for pattern in _SUFFIX_PATTERNS:
        regex = re.compile(pattern)

        # Check every FOV matches this suffix pattern
        matches: list[tuple[str, str, str]] = []  # (fov, prefix, suffix)
        for fov in fovs:
            m = regex.search(fov)
            if m is None:
                break
            prefix = fov[: m.start()]
            suffix = m.group()
            matches.append((fov, prefix, suffix))
        else:
            # All FOVs matched — check for multiple distinct prefixes
            prefixes = {prefix for _, prefix, _ in matches}
            if len(prefixes) < 2:
                continue

            condition_map: dict[str, str] = {}
            fov_name_map: dict[str, str] = {}
            for fov, prefix, suffix in matches:
                condition_map[fov] = prefix
                # Strip leading underscore from suffix for the site name
                site = suffix.lstrip("_")
                fov_name_map[fov] = site

            conditions = sorted(prefixes)
            return ConditionDetectionResult(
                condition_map=condition_map,
                fov_name_map=fov_name_map,
                conditions=conditions,
                pattern_used=pattern,
            )

    return None
