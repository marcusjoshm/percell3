---
title: "feat: Copy segmentation labels between FOVs"
type: feat
date: 2026-02-27
branch: feat/split-halo-condensate-analysis
---

# feat: Copy segmentation labels between FOVs

Copy a segmentation (label image + cell records) from one FOV to another. Primary use case: applying the original FOV's segmentation to derived FOVs (`bg_sub_`, `condensed_phase_`) that share the same geometry.

## Acceptance Criteria

- [x] Standalone `copy_labels_to_fov()` function copies labels and re-extracts cells on target
- [x] Napari dock widget with source/target FOV dropdowns and "Apply" button
- [x] Creates new segmentation run with provenance (`method: label_copy`, `source_fov_id`)
- [x] Errors if source FOV has no labels
- [x] Errors if source and target dimensions don't match
- [x] Overwrites existing labels on target silently (matches re-segmentation pattern)
- [x] Status label shows result (e.g., "Copied 42 cells from FOV_001 to bg_sub_FOV_001")
- [x] Tests for core copy function

## Implementation

### Phase 1: Core function

- [x] Add `copy_labels_to_fov()` to `src/percell3/segment/viewer/copy_labels_widget.py`

```python
def copy_labels_to_fov(
    store: ExperimentStore,
    source_fov_id: int,
    target_fov_id: int,
    channel: str,
) -> tuple[int, int]:
    """Copy segmentation labels from source FOV to target FOV.

    Reads source labels, creates a new segmentation run on the target,
    writes labels, and extracts cells via store_labels_and_cells().

    Returns:
        (run_id, cell_count)

    Raises:
        KeyError: If source FOV has no labels.
        ValueError: If source and target dimensions don't match.
    """
```

Logic:
1. `source_labels = store.read_labels(source_fov_id)` — raises KeyError if no labels
2. `target_info = store.get_fov_by_id(target_fov_id)`
3. Validate dimensions: `source_labels.shape == (target_info.height, target_info.width)`
4. `run_id = store.add_segmentation_run(channel, "label_copy", {"source_fov_id": source_fov_id})`
5. `cell_count = store_labels_and_cells(store, source_labels, target_info, run_id)`
6. Return `(run_id, cell_count)`

### Phase 2: Napari widget

- [x] Add `CopyLabelsWidget` class to the same file

```python
class CopyLabelsWidget:
    def __init__(self, viewer, store, fov_id, channel_names):
        # Source FOV dropdown (default: current fov_id)
        # Target FOV dropdown (all FOVs in experiment)
        # Channel dropdown (from channel_names)
        # Apply button
        # Status label
```

### Phase 3: Register in viewer

- [x] Modify `src/percell3/segment/viewer/_viewer.py` — add to `_launch()`

```python
copy_w = CopyLabelsWidget(viewer, store, fov_id, channel_names)
viewer.window.add_dock_widget(copy_w.widget, name="Copy Labels", area="right")
```

### Phase 4: Tests

- [x] Create `tests/test_segment/test_copy_labels_widget.py`
  - [x] Test happy path: copy labels from source to empty target
  - [x] Test cell count matches source
  - [x] Test error on source with no labels
  - [x] Test error on dimension mismatch
  - [x] Test overwrite existing labels on target
  - [x] Test segmentation run provenance metadata

## Key Patterns to Follow

| Pattern | Reference |
|---------|-----------|
| Widget class structure | `src/percell3/segment/viewer/bg_subtraction_widget.py` |
| Standalone function + widget | `subtract_background_to_derived_fov()` pattern |
| store_labels_and_cells | `src/percell3/segment/roi_import.py:14` |
| Dock widget registration | `src/percell3/segment/viewer/_viewer.py:138` |

## Gotchas (from learnings)

- **Use `store_labels_and_cells()`** as the canonical entry point — don't bypass with raw Zarr writes
- **`store_labels_and_cells` calls `delete_cells_for_fov()`** internally — handles cleanup of old cells
- **Lazy-import Qt widgets** inside `__init__`, not at module level
- **Use specific exception types**, never bare `except:`
- **Go through ExperimentStore public API** — no `store._conn` access

## References

- **Brainstorm:** `docs/brainstorms/2026-02-27-copy-segmentation-labels-between-fovs-brainstorm.md`
- **Widget pattern:** `src/percell3/segment/viewer/bg_subtraction_widget.py`
- **Label I/O:** `src/percell3/core/experiment_store.py:378` (`write_labels`), `:389` (`read_labels`)
- **Cell extraction:** `src/percell3/segment/roi_import.py:14` (`store_labels_and_cells`)
- **Learnings:** `docs/solutions/database-issues/zarr-sqlite-state-mismatch-re-thresholding.md`
- **Learnings:** `docs/solutions/architecture-decisions/viewer-module-code-review-findings.md`
