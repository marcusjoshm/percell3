---
title: "Small Segmentation Artifacts Need Minimum Area Filtering"
problem_type: logic-errors
component: [segment/label_processor, segment/_engine, segment/viewer]
symptoms:
  - "Small mask artifacts (a few pixels) counted as cells in per-cell analysis"
  - "Inflated cell counts from Cellpose debris detection"
root_cause: "No minimum area filter existed for post-segmentation cleanup"
resolution_type: feature
severity: medium
tags: [segmentation, cellpose, label-cleanup, napari]
date_solved: "2026-02-25"
---

# Small Segmentation Artifacts Need Minimum Area Filtering

## Problem Statement

After Cellpose segmentation, very small label masks (a few pixels) sometimes
get created that are clearly not real cells -- they are imaging artifacts, dust,
or noise that Cellpose's edge detection picks up. These small objects inflate
cell counts and can skew downstream measurements.

## Root Cause

No filtering mechanism existed to remove small objects after segmentation. The
existing `filter_edge_cells()` only handled cells near the image border, but
there was no area-based filter for artifact removal.

## Solution

Added `filter_small_cells()` to `label_processor.py`, following the same
pattern as `filter_edge_cells()`:

```python
def filter_small_cells(
    labels: np.ndarray,
    min_area: int,
) -> tuple[np.ndarray, int]:
    """Remove cells with area below min_area pixels."""
    small_labels = [prop.label for prop in regionprops(labels) if prop.area < min_area]
    if not small_labels:
        return labels.copy(), 0
    filtered = labels.copy()
    filtered[np.isin(filtered, small_labels)] = 0
    return filtered, len(small_labels)
```

### Integration Points

1. **`SegmentationParams`**: Added `min_area: int | None = None`
2. **`SegmentationEngine`**: Applied after `filter_edge_cells()` in the FOV loop
3. **CLI**: `--min-area` option on `percell3 segment` command
4. **Menu**: "Min cell area" prompt alongside edge margin in Segment and Workflow menus
5. **Napari widget**: "Label Cleanup" dock widget with both edge margin and min area spinboxes,
   sharing a single Preview/Apply workflow

### Filter Order

Edge cells are removed first, then small cells. This order matters because
edge cells may be partially cropped (appearing small), so removing edges first
avoids double-counting.

```python
# In SegmentationEngine.run():
if params.edge_margin is not None:
    labels, n_removed = filter_edge_cells(labels, params.edge_margin)
if params.min_area is not None:
    labels, n_small = filter_small_cells(labels, params.min_area)
```

## Prevention

- **Every post-segmentation filter** should have a corresponding
  `SegmentationParams` field so it can be controlled per-run.
- **Test filters independently** with dedicated unit tests in
  `test_label_processor.py` (not just as part of the full engine).
- **Log all filter removals** with counts for reproducibility.
- **Use the same pattern**: `(filtered_labels, removed_count)` return type,
  input not mutated, copy-on-write semantics.

## Affected Files

- `src/percell3/segment/label_processor.py` -- `filter_small_cells()`
- `src/percell3/segment/base_segmenter.py` -- `SegmentationParams.min_area`
- `src/percell3/segment/_engine.py` -- apply filter in FOV loop
- `src/percell3/segment/viewer/edge_removal_widget.py` -- "Label Cleanup" widget
- `src/percell3/cli/menu.py` -- menu prompts
- `src/percell3/cli/segment.py` -- `--min-area` CLI option
- `tests/test_segment/test_label_processor.py` -- 5 new tests

## Related

- [docs/plans/2026-02-25-feat-missing-percell-processing-steps-plan.md](../../plans/2026-02-25-feat-missing-percell-processing-steps-plan.md)
- [docs/brainstorms/2026-02-25-missing-percell-processing-steps-brainstorm.md](../../brainstorms/2026-02-25-missing-percell-processing-steps-brainstorm.md)
