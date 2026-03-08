---
status: pending
priority: p2
issue_id: 155
tags: [code-review, quality, io]
dependencies: []
---

# stitch_tiles Doesn't Enforce 2D Input Arrays

## Problem Statement

`stitch_tiles()` at line 438 uses `tile_images[0].shape[:2]` to get tile dimensions but never validates that tiles are actually 2D. If a 3D array reaches this function (e.g., Z-projection skipped due to bug), the canvas is created as 2D but tile assignment would fail with an unhelpful broadcasting error.

## Findings

- **Source**: kieran-python-reviewer
- **Location**: `src/percell3/io/engine.py:438`

## Proposed Solutions

### Option A: Add explicit ndim check (Recommended)
- **Effort**: Small
- **Risk**: Low

```python
if tile_images[0].ndim != 2:
    raise ValueError(
        f"Expected 2D tile images, got {tile_images[0].ndim}D "
        f"(shape={tile_images[0].shape}). Apply Z-projection first."
    )
```

## Technical Details

- **Affected files**: `src/percell3/io/engine.py`

## Acceptance Criteria

- [ ] `stitch_tiles` raises clear ValueError for 3D input
- [ ] Test added

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-02 | Created from code review | Found by kieran-python-reviewer |
