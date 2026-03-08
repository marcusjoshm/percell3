---
status: pending
priority: p2
issue_id: "009"
tags: [code-review, quality]
dependencies: []
---

# Duplicated Code Patterns

## Problem Statement

Several code patterns in `percell3.core` are duplicated across multiple locations, violating DRY (Don't Repeat Yourself). This duplication means that bug fixes or schema changes must be applied in multiple places, increasing the risk of inconsistencies and maintenance burden. The duplications span both the SQL query layer and the zarr I/O layer.

## Findings

1. **ChannelConfig row mapping** is duplicated between `select_channels` and `select_channel_by_name` in `queries.py:68-100`. Both functions contain identical logic for converting a SQLite row into a `ChannelConfig` dataclass.

2. **RegionInfo row mapping** is duplicated between `select_regions` and `select_region_by_name`. Same pattern as above: identical row-to-dataclass conversion in two places.

3. **image_group_path and label_group_path** in `zarr_io.py:36-55` are character-for-character identical functions (or nearly so), differing only in intent but not in implementation.

4. **_build_multiscales_label and _build_multiscales_mask** share the vast majority of their structure, differing only in minor details (e.g., metadata keys or group names). The shared logic for building OME-NGFF multiscale metadata is duplicated.

## Proposed Solutions

### Option 1

Extract small, focused helper functions for each duplication:

```python
# queries.py
def _row_to_channel(row: sqlite3.Row) -> ChannelConfig:
    """Convert a SQLite row to a ChannelConfig dataclass."""
    return ChannelConfig(
        channel_id=row["channel_id"],
        name=row["name"],
        # ... remaining fields
    )

def _row_to_region(row: sqlite3.Row) -> RegionInfo:
    """Convert a SQLite row to a RegionInfo dataclass."""
    return RegionInfo(
        region_id=row["region_id"],
        name=row["name"],
        # ... remaining fields
    )
```

```python
# zarr_io.py
def _data_group_path(region_id: int, group_type: str, name: str) -> str:
    """Build a zarr group path for image, label, or mask data."""
    return f"region_{region_id}/{group_type}/{name}"
```

```python
# zarr_io.py
def _build_2d_multiscales(
    group: zarr.Group,
    data: np.ndarray,
    name: str,
    axes_type: str,  # "label" or "mask"
    # ... shared parameters
) -> None:
    """Build OME-NGFF multiscale metadata for a 2D dataset."""
    # Shared implementation
```

### Option 2

For the zarr path functions, if `image_group_path` and `label_group_path` are truly identical, collapse them into a single function. If they are expected to diverge in the future (e.g., labels get stored in a different hierarchy), keep them separate but have both call a shared private helper.

## Technical Details

- Files affected:
  - `src/percell3/core/queries.py` (lines 68-100 and surrounding region query functions)
  - `src/percell3/core/zarr_io.py` (lines 36-55 for path functions, and the `_build_multiscales_*` functions)
- The row mapping helpers should be private functions (prefixed with `_`) since they are internal implementation details.
- When unifying `_build_multiscales_label` and `_build_multiscales_mask`, use parameters to capture the differences rather than inheritance or complex abstractions. Keep it simple.
- Ensure that any extracted helper has a clear docstring and is tested independently.

## Acceptance Criteria

- [ ] `_row_to_channel()` helper extracted and used by both `select_channels` and `select_channel_by_name`
- [ ] `_row_to_region()` helper extracted and used by both `select_regions` and `select_region_by_name`
- [ ] `image_group_path` and `label_group_path` share a common implementation or are unified
- [ ] `_build_multiscales_label` and `_build_multiscales_mask` share a common `_build_2d_multiscales` helper
- [ ] All existing tests pass without modification (refactoring should not change behavior)
- [ ] No remaining character-for-character duplicated blocks

## Work Log

### 2026-02-12 - Code Review Discovery

Identified during code review of `percell3.core`. Four distinct duplication patterns found across `queries.py` and `zarr_io.py`. Each duplication is a maintenance liability: if the schema or zarr format changes, forgetting to update one copy will introduce subtle bugs.
