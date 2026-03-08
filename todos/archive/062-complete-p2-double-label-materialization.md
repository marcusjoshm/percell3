---
status: complete
priority: p2
issue_id: "062"
tags: [code-review, napari-viewer, performance, memory]
dependencies: []
---

# Double Label Array Materialization for Change Detection — 800MB for 10K x 10K

## Problem Statement
In `_viewer.py`, the label array is fully materialized into memory, and then a copy is made for change detection (`np.array_equal(original, edited)`). For a 10K x 10K int32 label image, this means ~400MB x 2 = 800MB just for labels. The change detection also does a full O(n) comparison even when labels haven't been touched.

## Findings
- **File:** `src/percell3/segment/viewer/_viewer.py` — `_load_label_layer()` and `_launch()` change detection
- Flagged by: performance-oracle (CRITICAL-1, CRITICAL-2)
- `read_labels()` already materializes the array
- A second copy is stored just for `np.array_equal()`
- On large images, this can cause OOM or significant swap pressure

## Proposed Solutions
### Option 1 (Recommended): Use hash-based change detection
Compute a hash (e.g., `hashlib.sha256(labels.tobytes())`) of the original labels. After napari closes, hash the potentially-edited labels and compare hashes. This avoids storing a full copy. Cost: one extra pass on close.

### Option 2: Use napari's undo history
Check if napari's Labels layer has been modified via its `data_setitem` events or undo stack, avoiding comparison entirely.

### Option 3: Accept the memory cost, document the limitation
For typical microscopy images (2K x 2K), the cost is ~32MB which is acceptable. Add a warning for large images.

## Acceptance Criteria
- [ ] Only one copy of the label array in memory during viewer session
- [ ] Change detection works without full array duplication
- [ ] Memory usage documented/tested for large images
