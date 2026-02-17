---
status: pending
priority: p2
issue_id: "052"
tags: [code-review, segment, performance, memory]
dependencies: []
---

# Redundant int32 `astype` Copies Across Label Pipeline

## Problem Statement

Label arrays are converted to `int32` up to **3 times** in the segmentation pipeline. Each `astype(np.int32)` allocates a full copy even when the data is already int32. For a 2048x2048 label image, each copy allocates 16 MB — totaling 32-48 MB of unnecessary transient allocation per region.

## Findings

Three locations perform `astype(np.int32)` on the same data path:

1. **`cellpose_adapter.py:93`** — `masks.astype(np.int32)` after Cellpose returns
2. **`roi_import.py:62`** — `labels.astype(np.int32)` on import (always copies)
3. **`zarr_io.py:272`** — `data.astype(np.int32)` inside `write_labels`

Additionally, `roi_import.py:178-181` has a redundant conditional where both branches do `masks.astype(np.int32)`:
```python
if not np.issubdtype(masks.dtype, np.integer):
    masks = masks.astype(np.int32)
else:
    masks = masks.astype(np.int32)
```

## Proposed Solutions

### Option 1 (Recommended): Use `np.asarray()` for zero-copy

Replace `data.astype(np.int32)` with `np.asarray(data, dtype=np.int32)` at each location. `np.asarray` returns the input unchanged (no copy) when the dtype already matches, and converts only when necessary.

```python
# zarr_io.py:272
label_data = np.asarray(data, dtype=np.int32)

# roi_import.py:62
labels_int32 = np.asarray(labels, dtype=np.int32)

# roi_import.py:178-181 (also fixes redundant if/else)
masks = np.asarray(masks, dtype=np.int32)
```

- Pros: Zero-copy when already int32, minimal code change
- Cons: None
- Effort: Small (4 one-line changes)
- Risk: Low

## Acceptance Criteria

- [ ] No redundant array copies when labels are already int32
- [ ] `roi_import.py` redundant if/else branches collapsed to one line
- [ ] All tests pass

## Work Log

### 2026-02-16 — Code Review Discovery
Identified by performance-oracle and code-simplicity-reviewer. Estimated 32-48 MB unnecessary allocation per region for 2048x2048 images.
