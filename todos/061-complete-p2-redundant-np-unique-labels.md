---
status: complete
priority: p2
issue_id: "061"
tags: [code-review, napari-viewer, performance]
dependencies: []
---

# Redundant `np.unique()` on Labels — O(n log n) for Available Data

## Problem Statement
In `src/percell3/segment/viewer/_viewer.py:276` (or nearby in save path), `np.unique()` is called on the label array to count unique labels. This is O(n log n) and potentially very expensive for large images. The cell count is already computed by `extract_cells()` or available from the segmentation run metadata.

## Findings
- **File:** `src/percell3/segment/viewer/_viewer.py` — save path
- Flagged by: performance-oracle (CRITICAL-3), code-simplicity-reviewer
- `np.unique()` on a 10K x 10K int32 array takes ~2 seconds
- The information is already available from `cell_count` returned by `extract_cells()`

## Proposed Solutions
### Option 1 (Recommended): Use cell_count from extract_cells return value
Remove `np.unique()` call. Use the count already returned by cell extraction.

## Acceptance Criteria
- [ ] `np.unique()` call removed from save path
- [ ] Cell count sourced from `extract_cells()` or equivalent
- [ ] No performance regression on large images
