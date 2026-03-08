---
title: "feat: Cellpose segmentation dock widget in napari viewer"
type: feat
date: 2026-02-20
---

# feat: Cellpose Segmentation Dock Widget in Napari Viewer

## Overview

Add a cellpose segmentation dock widget to the napari viewer (menu item 4) so users can run cellpose interactively with parameter tuning, plus a "Delete Cell" button for quick cleanup. The official `cellpose-napari` plugin (v0.2.0) is abandoned and incompatible with cellpose 4.x / napari 0.6+, so we build a custom widget using PerCell 3's existing CellposeAdapter and dock widget patterns.

## Problem Statement / Motivation

Currently, cellpose segmentation is only available through the CLI (menu item 3) as a batch operation. Users cannot:
- Tune cellpose parameters interactively while seeing results in real-time
- Run cellpose on a single FOV from within the napari viewer
- Quickly delete bad segmentations (e.g., debris, merged cells) with a button

The `cellpose-napari` plugin is not viable:
- v0.2.0 uses removed `Cellpose` class (cellpose 4.x renamed to `CellposeModel`)
- Uses deprecated npe1 plugin engine (will break in napari 0.7.0)
- Model list is outdated (no `cpsam`)

PerCell 3 already has all the building blocks: `CellposeAdapter` (cellpose 4.x compatible), `save_edited_labels()` (labels -> zarr + cells table), and a QWidget dock widget pattern (`threshold_viewer.py`).

## Proposed Solution

### Architecture

```
menu item 4 (_view_napari)
    |
    v
_launch() in _viewer.py
    |-- loads channel images
    |-- loads segmentation labels
    |-- loads threshold masks
    |-- NEW: adds CellposeWidget dock widget
    |-- NEW: adds DeleteCellWidget dock widget
    |-- napari.run() (blocks)
    |-- save-back on close (existing)
```

The cellpose widget runs segmentation via `@thread_worker` (async, non-blocking UI) and immediately persists results to ExperimentStore when complete. The delete cell widget uses napari's `fill()` API for undo-compatible cell deletion.

### New files

| File | Purpose |
|------|---------|
| `src/percell3/segment/viewer/cellpose_widget.py` | CellposeWidget QWidget — model/param controls + Run button |
| `src/percell3/segment/viewer/edit_widget.py` | EditWidget QWidget — Delete Cell button |
| `tests/test_segment/test_cellpose_widget.py` | Unit tests for widget logic (parameter validation, model selection) |
| `tests/test_segment/test_edit_widget.py` | Unit tests for delete cell logic |

### Modified files

| File | Changes |
|------|---------|
| `src/percell3/segment/viewer/_viewer.py` | Add dock widgets in `_launch()`, pass store/fov/condition context |
| `src/percell3/segment/cellpose_adapter.py` | Accept custom model paths (file paths bypass `KNOWN_CELLPOSE_MODELS` check) |
| `src/percell3/segment/base_segmenter.py` | Expand `cellprob_threshold` validator range from [-6,6] to [-8,8] |
| `src/percell3/core/queries.py` | Fix `delete_cells_for_fov` to also delete particles (pre-existing bug) |
| `src/percell3/segment/roi_import.py` | Add `delete_cells_for_fov` call in `store_labels_and_cells` before inserting new cells |

## Implementation Phases

### Phase 1: Bug fixes and prerequisites

Fix pre-existing data integrity issues that the dock widget will expose.

- [x] **Fix `delete_cells_for_fov` to cascade particles** — `queries.py`
  - Add `DELETE FROM particles WHERE cell_id IN (SELECT id FROM cells WHERE fov_id = ?)` before the measurements delete
  - This prevents orphan particle rows when re-segmenting
- [x] **Fix `store_labels_and_cells` to delete old cells** — `roi_import.py`
  - Call `store.delete_cells_for_fov(fov, condition)` before `store.add_cells(cells)`
  - This fixes duplicate cell records when saving labels from napari
- [x] **Expand cellprob_threshold validator** — `base_segmenter.py`
  - Change range from [-6, 6] to [-8, 8] (cellpose 4.x supports this range)
- [x] **Support custom model paths in CellposeAdapter** — `cellpose_adapter.py`
  - If `model_name` is a filesystem path (contains `/` or `\`), bypass `KNOWN_CELLPOSE_MODELS` check
  - Pass as `pretrained_model=model_name` to `CellposeModel()`
- [x] Tests for all above fixes

### Phase 2: CellposeWidget dock widget

The main segmentation widget, docked on the right side of the napari viewer.

- [x] **Create `cellpose_widget.py`** with QWidget subclass `CellposeWidget`
  - Constructor takes `viewer`, `store`, `fov`, `condition`, `bio_rep`, list of channel names
  - **Controls**:
    - Model ComboBox: `cpsam` (default), `cyto3`, `cyto2`, `nuclei`, `custom...`
    - Custom model FileEdit (hidden until "custom..." selected)
    - Primary channel ComboBox (populated from loaded image layer names)
    - Nucleus channel ComboBox (`None` + channel names, default `None`)
    - Diameter SpinBox (1-500, default 30)
    - Cell probability threshold FloatSlider (-8 to 8, step 0.2, default 0.0)
    - Flow threshold FloatSlider (0 to 3, step 0.05, default 0.4)
    - GPU status label (auto-detected: "GPU: CUDA" / "GPU: MPS" / "CPU only")
    - "Run Segmentation" QPushButton
    - Status label (shows "Running...", "Done: 142 cells", errors)
  - **Run button callback**:
    1. Disable button, show "Running..."
    2. Launch `@thread_worker` that calls `CellposeAdapter.segment()`
    3. On completion:
       - Delete existing cells for this FOV (`store.delete_cells_for_fov`)
       - Write labels to zarr (`store.write_labels`)
       - Extract cells + insert (`store_labels_and_cells`)
       - Create segmentation run record
       - Update the "segmentation" Labels layer in the viewer
       - Auto-measure all channels (`Measurer.measure_fov` for each channel)
       - Re-enable button, show "Done: N cells"
    4. On error: show error message, re-enable button
  - **Thread cancellation**: connect to viewer `closing` event; if worker is running, call `worker.quit()`
- [x] Tests for CellposeWidget (mock cellpose, verify store calls, verify layer update)

### Phase 3: EditWidget dock widget (Delete Cell)

A small widget docked below the cellpose widget.

- [x] **Create `edit_widget.py`** with QWidget subclass `EditWidget`
  - Constructor takes `viewer`
  - **Controls**:
    - "Delete Cell" QPushButton
    - Status label showing selected label value
  - **Delete Cell callback**:
    1. Find the Labels layer named "segmentation"
    2. Read `labels_layer.selected_label` (the label value under the last pick-mode click)
    3. If selected_label == 0, show "No cell selected"
    4. Use `labels_layer.fill(coord, 0)` where coord is any pixel of that label — this integrates with napari's undo stack (Ctrl+Z works)
    5. Update status: "Deleted cell #N"
  - **Alternative approach if `fill()` doesn't work for whole-label deletion**: use `labels_layer.data[labels_layer.data == selected_label] = 0` wrapped in `labels_layer.block_history()` context manager, then call `labels_layer.refresh()`
- [x] Tests for EditWidget logic

### Phase 4: Wire into `_viewer.py`

- [x] **Modify `_launch()`** to add both dock widgets after creating the viewer
  ```python
  # After loading labels...
  cellpose_w = CellposeWidget(viewer, store, fov, condition, bio_rep, channel_names)
  viewer.window.add_dock_widget(cellpose_w, name="Cellpose", area="right")

  edit_w = EditWidget(viewer)
  viewer.window.add_dock_widget(edit_w, name="Edit Labels", area="right")
  ```
- [x] Ensure the existing save-back still works (hash comparison detects widget-initiated changes)
- [x] Integration test: launch viewer with dock widgets, verify they initialize without error

## Acceptance Criteria

- [ ] Opening napari via menu item 4 shows the Cellpose dock widget on the right
- [ ] User can select model, diameter, thresholds, and channel, then click "Run Segmentation"
- [ ] Cellpose runs asynchronously (napari UI stays responsive)
- [ ] After cellpose completes, labels appear in the viewer and are persisted to ExperimentStore
- [ ] Segmentation run is recorded in `segmentation_runs` table with correct parameters
- [ ] Cells are extracted and stored in `cells` table
- [ ] Auto-measurement runs after segmentation (measurements table populated)
- [ ] Re-segmenting deletes old cells, measurements, particles, and tags before inserting new ones
- [ ] "Delete Cell" button removes all pixels of the selected label (sets to 0)
- [ ] Delete Cell is undoable (Ctrl+Z restores the cell)
- [ ] Closing napari while cellpose is running shows a warning or cancels gracefully
- [ ] GPU is auto-detected and displayed in the widget
- [ ] Custom model paths work (file picker, bypasses known-models check)
- [ ] All existing tests still pass (no regressions in batch segmentation or viewer save-back)

## Dependencies & Risks

**Dependencies:**
- napari >= 0.6.0 (for `thread_worker`, dock widgets)
- PyQt5 >= 5.15 (already in `[napari]` extras)
- cellpose >= 3.0 (already installed, 4.0.8 in current env)

**Risks:**
- `thread_worker` pattern is new to the codebase — no existing example to follow. Mitigated by following cellpose-napari's proven pattern.
- GPU memory: cellpose model + large FOV image can exhaust GPU memory. Mitigated by `del CP` after eval and error handling.
- Qt event loop complexity: dock widget callbacks interact with the blocking `napari.run()` loop. This is the standard napari pattern (threshold_viewer already does this).

## References & Research

### Internal
- Existing viewer: `src/percell3/segment/viewer/_viewer.py`
- Dock widget pattern: `src/percell3/measure/threshold_viewer.py`
- CellposeAdapter: `src/percell3/segment/cellpose_adapter.py`
- SegmentationEngine: `src/percell3/segment/_engine.py`
- Save-back primitive: `src/percell3/segment/roi_import.py:store_labels_and_cells()`
- Brainstorm: `docs/brainstorms/2026-02-13-cellpose-segmentation-workflow-brainstorm.md`

### Institutional learnings
- Viewer P1 bugs: `docs/solutions/architecture-decisions/viewer-module-code-review-findings.md`
- Cellpose 4.0 API: `docs/solutions/integration-issues/cellpose-4-0-api-breaking-change.md`
- Viewer merge conflicts: `docs/solutions/integration-issues/napari-viewer-datamodel-merge-api-conflicts.md`

### External
- cellpose-napari source (reference for widget pattern): `github.com/MouseLand/cellpose-napari`
- napari dock widgets: `napari.org/dev/howtos/extending/magicgui.html`
- napari thread_worker: `napari.qt.threading.thread_worker`
- napari Labels API: `napari.org/dev/api/napari.layers.Labels.html`
