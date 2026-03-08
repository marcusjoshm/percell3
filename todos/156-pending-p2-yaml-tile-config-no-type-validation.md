---
status: pending
priority: p2
issue_id: 156
tags: [code-review, security, io]
dependencies: []
---

# No Type Validation on YAML-Deserialized tile_config Fields

## Problem Statement

In `src/percell3/io/serialization.py:140-148`, values from `yaml.safe_load()` are passed directly to `TileConfig()` without type checking. YAML can produce unexpected types: `grid_rows: "3"` passes a string, `grid_rows: [1,2]` passes a list, `grid_rows: 1.5` passes a float. These cause confusing runtime errors downstream.

## Findings

- **Source**: security-sentinel
- **Location**: `src/percell3/io/serialization.py:140-148`

## Proposed Solutions

### Option A: Add type checks before TileConfig construction (Recommended)
- **Effort**: Small
- **Risk**: Low

```python
if tc_tile is not None:
    if not isinstance(tc_tile, dict):
        raise ValueError("tile_config must be a mapping")
    for key in ("grid_rows", "grid_cols"):
        if not isinstance(tc_tile.get(key), int):
            raise ValueError(f"tile_config.{key} must be an integer")
    for key in ("grid_type", "order"):
        if not isinstance(tc_tile.get(key), str):
            raise ValueError(f"tile_config.{key} must be a string")
```

## Technical Details

- **Affected files**: `src/percell3/io/serialization.py`

## Acceptance Criteria

- [ ] YAML with `grid_rows: "3"` raises clear ValueError
- [ ] YAML with `grid_rows: [1,2]` raises clear ValueError
- [ ] Valid YAML still loads correctly
- [ ] Test added

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-02 | Created from code review | Found by security-sentinel |
