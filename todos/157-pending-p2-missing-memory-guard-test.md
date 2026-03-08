---
status: pending
priority: p2
issue_id: 157
tags: [code-review, quality, testing, io]
dependencies: []
---

# Missing Memory Guard Test for stitch_tiles

## Problem Statement

The `stitch_tiles()` function has a 2 GB memory guard (`_MAX_CANVAS_BYTES`) that raises ValueError when the stitched canvas would exceed the limit. This safety-critical path has no test coverage.

## Findings

- **Source**: kieran-python-reviewer
- **Location**: `src/percell3/io/engine.py:447-456`

## Proposed Solutions

### Option A: Monkeypatch threshold to small value (Recommended)
- **Effort**: Small
- **Risk**: Low

```python
def test_memory_guard_raises(self, monkeypatch):
    import percell3.io.engine as engine_mod
    monkeypatch.setattr(engine_mod, "_MAX_CANVAS_BYTES", 1024)
    tiles = [np.zeros((64, 64), dtype=np.uint16)] * 4
    config = TileConfig(grid_rows=2, grid_cols=2, grid_type="row_by_row", order="right_and_down")
    with pytest.raises(ValueError, match="exceeding 2 GB limit"):
        stitch_tiles(tiles, config)
```

## Technical Details

- **Affected files**: `tests/test_io/test_engine.py`

## Acceptance Criteria

- [ ] Test verifies memory guard raises ValueError with descriptive message
- [ ] Test uses monkeypatch to avoid needing actual large allocations

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-02 | Created from code review | Found by kieran-python-reviewer |
