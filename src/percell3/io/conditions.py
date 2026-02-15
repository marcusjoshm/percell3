"""Condition auto-detection from region names."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Suffix patterns that typically identify site/field-of-view within a condition.
# Tried in order; first pattern where ALL regions match wins.
_SUFFIX_PATTERNS = [
    r"_s\d+$",
    r"_\d+$",
    r"_fov\d+$",
    r"_field\d+$",
    r"_site\d+$",
]


@dataclass(frozen=True)
class ConditionDetectionResult:
    """Result of automatic condition detection from region names.

    Attributes:
        condition_map: Maps original region token to its detected condition name.
        region_name_map: Maps original region token to a cleaned site/FOV name.
        conditions: Unique condition names, sorted alphabetically.
        pattern_used: The suffix regex pattern that matched (for display).
    """

    condition_map: dict[str, str]
    region_name_map: dict[str, str]
    conditions: list[str]
    pattern_used: str


def detect_conditions(regions: list[str]) -> ConditionDetectionResult | None:
    """Analyze region names to detect condition groupings.

    Heuristic:
    1. Try each suffix pattern (e.g. ``_s\\d+$``, ``_\\d+$``).
    2. If ALL region names match a pattern AND have multiple distinct
       prefixes, conditions are detected.
    3. Returns None if no pattern matches or only one prefix found.

    Args:
        regions: List of region name strings (e.g. from ScanResult.regions).

    Returns:
        A ConditionDetectionResult if conditions were detected, else None.
    """
    if not regions:
        return None

    for pattern in _SUFFIX_PATTERNS:
        regex = re.compile(pattern)

        # Check every region matches this suffix pattern
        matches: list[tuple[str, str, str]] = []  # (region, prefix, suffix)
        for region in regions:
            m = regex.search(region)
            if m is None:
                break
            prefix = region[: m.start()]
            suffix = m.group()
            matches.append((region, prefix, suffix))
        else:
            # All regions matched — check for multiple distinct prefixes
            prefixes = {prefix for _, prefix, _ in matches}
            if len(prefixes) < 2:
                continue

            condition_map: dict[str, str] = {}
            region_name_map: dict[str, str] = {}
            for region, prefix, suffix in matches:
                condition_map[region] = prefix
                # Strip leading underscore from suffix for the site name
                site = suffix.lstrip("_")
                region_name_map[region] = site

            conditions = sorted(prefixes)
            return ConditionDetectionResult(
                condition_map=condition_map,
                region_name_map=region_name_map,
                conditions=conditions,
                pattern_used=pattern,
            )

    return None
