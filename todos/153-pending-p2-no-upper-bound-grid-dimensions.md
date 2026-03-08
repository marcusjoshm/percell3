---
status: pending
priority: p2
issue_id: 153
tags: [code-review, security, performance, io]
dependencies: []
---

# No Upper-Bound Validation on Grid Dimensions in TileConfig

## Problem Statement

`TileConfig.__post_init__` only validates that `grid_rows` and `grid_cols` are >= 1. There is no upper bound. A value like `grid_rows=1000000, grid_cols=1000000` causes `build_tile_grid()` to pre-allocate a list of 1 trillion entries, crashing with OOM before the 2 GB memory guard in `stitch_tiles` fires.

## Findings

- **Source**: security-sentinel, performance-oracle
- **Location**: `src/percell3/io/models.py:66-75`, `src/percell3/io/engine.py:371-373`
- **Evidence**: `positions: list[tuple[int, int]] = [(0, 0)] * total` where total = rows * cols with no upper bound

## Proposed Solutions

### Option A: Add _MAX_GRID_DIM constant (Recommended)
- **Pros**: Simple, single fix addresses 3 findings (model, CLI, menu)
- **Cons**: Arbitrary limit, but 100 covers all real microscopy tile scans
- **Effort**: Small
- **Risk**: Low

```python
_MAX_GRID_DIM = 100

def __post_init__(self) -> None:
    if not (1 <= self.grid_rows <= _MAX_GRID_DIM):
        raise ValueError(f"grid_rows must be 1-{_MAX_GRID_DIM}, got {self.grid_rows}")
    if not (1 <= self.grid_cols <= _MAX_GRID_DIM):
        raise ValueError(f"grid_cols must be 1-{_MAX_GRID_DIM}, got {self.grid_cols}")
```

## Technical Details

- **Affected files**: `src/percell3/io/models.py`

## Acceptance Criteria

- [ ] `TileConfig(grid_rows=101, grid_cols=1)` raises ValueError
- [ ] `TileConfig(grid_rows=100, grid_cols=100)` succeeds
- [ ] Test added for upper-bound validation

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-02 | Created from code review | Found by security-sentinel and performance-oracle |
