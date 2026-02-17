---
status: pending
priority: p2
issue_id: "064"
tags: [code-review, napari-viewer, duplication, segment]
dependencies: []
---

# Duplicate Label-Save Logic Between Viewer and RoiImporter

## Problem Statement
Both `_save_edited_labels()` in the viewer module and `RoiImporter` in `roi_import.py` implement the same pipeline: create segmentation run -> write labels -> extract cells. This duplication means fixes to one path may not be applied to the other, and the logic can diverge over time.

## Findings
- **File:** `src/percell3/segment/viewer/_viewer.py` — `_save_edited_labels()`
- **File:** `src/percell3/segment/roi_import.py` — `import_rois()` method
- Flagged by: agent-native-reviewer, kieran-python-reviewer
- Both create a segmentation run with `add_segmentation_run()`
- Both call `write_labels()` + `extract_cells()` + `insert_cells()`
- Divergence risk is high

## Proposed Solutions
### Option 1 (Recommended): Extract shared `persist_labels()` function
Create a `persist_labels(store, region, condition, channel, labels, model_name)` function in the segment module that both viewer and RoiImporter call.

### Option 2: Have RoiImporter use the viewer's save function
Make `_save_edited_labels` public and have RoiImporter delegate to it. But this creates an odd dependency direction.

## Acceptance Criteria
- [ ] Single code path for persisting labels to the store
- [ ] Both viewer and RoiImporter use the shared function
- [ ] Tests exercise the shared function directly
