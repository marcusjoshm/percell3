---
status: complete
priority: p1
issue_id: "109"
tags: [code-review, segment, performance, bug]
dependencies: []
---

# filter_edge_cells() mutates input and has O(k*m) performance

## Problem Statement

Two issues with `filter_edge_cells()`:

1. **In-place mutation**: The function mutates the input `labels` array and returns it, but the return type `tuple[ndarray, int]` implies it returns a new array. The engine at `_engine.py:134` passes the array without copying. While this works today (labels are written to zarr immediately after), the contract is misleading and will cause bugs when someone calls it expecting the original to be preserved.

2. **O(k*m) performance**: `labels[labels == prop.label] = 0` performs a full array scan for every edge cell. For a 2048x2048 image with 50 edge cells, this does ~210M pixel comparisons. Using `np.isin()` to batch the removal into a single pass would be ~25x faster.

## Findings

- **Found by:** kieran-python-reviewer, performance-oracle
- **Location:** `src/percell3/segment/label_processor.py:31-36`
- Tests defensively use `.copy()` (lines 148, 159, 170, 180, 197) but production code does not

## Proposed Solutions

### Solution A: Copy input + use np.isin (Recommended)
```python
def filter_edge_cells(labels, edge_margin=0):
    if labels.max() == 0:
        return labels.copy(), 0
    filtered = labels.copy()
    h, w = filtered.shape
    edge_labels = []
    for prop in regionprops(filtered):
        min_row, min_col, max_row, max_col = prop.bbox
        if (min_row <= edge_margin or min_col <= edge_margin
                or max_row >= h - edge_margin or max_col >= w - edge_margin):
            edge_labels.append(prop.label)
    if not edge_labels:
        return filtered, 0
    filtered[np.isin(filtered, edge_labels)] = 0
    return filtered, len(edge_labels)
```
- **Effort:** Small | **Risk:** Low

## Acceptance Criteria

- [ ] Function returns a new array (does not mutate input)
- [ ] Uses `np.isin()` for single-pass removal
- [ ] Existing tests pass without `.copy()` calls
- [ ] Performance acceptable for 4096x4096 images

## Work Log

- 2026-02-25: Identified during code review
