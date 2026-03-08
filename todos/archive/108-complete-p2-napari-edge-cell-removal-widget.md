---
status: complete
priority: p2
issue_id: "108"
tags: [code-review, segment, napari, widget, ux]
dependencies: []
---

# Create napari widget for edge cell removal during segmentation

## Problem Statement

Edge cell removal is currently only available as a parameter during batch segmentation (CLI flag `--edge-margin` or interactive menu prompt). When using the napari viewer for interactive segmentation review, there is no way to visually preview and adjust edge cell removal. Users want to see which cells would be removed at different margin values before committing.

A napari widget should allow the user to:
1. Set an edge margin distance (slider or spinbox)
2. See which cells are within the margin (highlighted in red/overlay)
3. Apply the removal and update the label image

## Findings

- **Found by:** User testing
- **Location:**
  - Existing edge cell removal: `src/percell3/segment/label_processor.py:filter_edge_cells()`
  - Existing napari viewer: `src/percell3/segment/viewer/`
  - Segmentation viewer launch: `src/percell3/segment/viewer/napari_viewer.py`
  - Surface plot widget example: `src/percell3/segment/viewer/surface_plot_widget.py`

## Proposed Solutions

### Solution A: Add edge removal widget to existing segmentation viewer (Recommended)
1. Create `src/percell3/segment/viewer/edge_removal_widget.py` — a `QWidget` with:
   - Spinbox for edge margin (0-100 px)
   - "Preview" button that highlights edge cells in a separate labels layer (red overlay)
   - "Apply" button that removes edge cells from the label image
   - Count display showing how many cells would be / were removed
2. Add the widget to the napari viewer dock when launched from `_view_napari()`
3. Reuse `filter_edge_cells()` from `label_processor.py` for the actual filtering
- **Effort:** Medium | **Risk:** Low

### Solution B: Standalone napari plugin
- Register as a napari plugin contribution point
- More discoverable but more complex setup
- **Effort:** Medium-Large | **Risk:** Medium

## Acceptance Criteria

- [ ] Widget appears in napari when viewing segmentation labels
- [ ] Spinbox controls edge margin value
- [ ] Preview shows which cells will be removed (visual highlight)
- [ ] Apply button removes the cells from label image
- [ ] Count of removed cells displayed
- [ ] Updated labels saved when napari window closes
- [ ] Works with the existing label save flow in the viewer

## Work Log

- 2026-02-25: Identified during user interface testing
