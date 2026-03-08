---
title: "feat: Add edge cell removal, Gaussian smoothing, and group labels in exports"
type: feat
date: 2026-02-25
---

# feat: Add edge cell removal, Gaussian smoothing, and group labels in exports

## Overview

Three processing features from the original PerCell that are missing in PerCell 3:

1. **Edge cell removal** — post-segmentation filter that removes partial cells touching the image border
2. **Gaussian smoothing before thresholding** — optional pre-processing to reduce noise before Otsu/other threshold methods
3. **Cell group labels in all exports** — include GMM-based group assignments in wide CSV, Prism, and particle exports

## Proposed Solution

### Feature 1: Edge Cell Removal

Add a `filter_edge_cells()` function to `label_processor.py` and call it in the segmentation engine between `segment()` and `write_labels()`.

**Algorithm:**
1. Run `skimage.measure.regionprops(labels)` to get bounding boxes
2. For each cell, check if bbox is within `edge_margin` pixels of any image border
3. Zero out those label values in the label array
4. Return filtered labels and count of removed cells

**Why not `skimage.segmentation.clear_border()`?** It only handles margin=0 (cells directly touching the border). We need configurable margin support.

**Files to modify:**

| File | Change |
|------|--------|
| `src/percell3/segment/label_processor.py` | Add `filter_edge_cells(labels, edge_margin) -> tuple[ndarray, int]` |
| `src/percell3/segment/base_segmenter.py:37` | Add `remove_edge_cells: bool = False` and `edge_margin: int = 0` to `SegmentationParams` |
| `src/percell3/segment/_engine.py:129` | Call `filter_edge_cells()` between segment and write_labels when `remove_edge_cells=True` |
| `src/percell3/segment/_engine.py:86` | Forward `remove_edge_cells` and `edge_margin` kwargs |
| `src/percell3/cli/menu.py` (segment handler) | Add edge cell removal option to interactive segmentation menu |
| `src/percell3/cli/segment.py` | Add `--edge-margin` CLI flag |

**Implementation — `label_processor.py`:**

```python
def filter_edge_cells(
    labels: np.ndarray,
    edge_margin: int = 0,
) -> tuple[np.ndarray, int]:
    """Remove cells whose bounding box is within edge_margin of the image border.

    Args:
        labels: 2D integer label image (0 = background).
        edge_margin: Pixels from border. 0 = only cells touching edge.

    Returns:
        Tuple of (filtered_labels, removed_count).
    """
    from skimage.measure import regionprops

    h, w = labels.shape
    removed = 0
    for prop in regionprops(labels):
        min_row, min_col, max_row, max_col = prop.bbox
        if (min_row <= edge_margin or min_col <= edge_margin
                or max_row >= h - edge_margin or max_col >= w - edge_margin):
            labels[labels == prop.label] = 0
            removed += 1
    return labels, removed
```

**Implementation — `_engine.py` (between segment and write_labels):**

```python
# After: labels = segmenter.segment(image, params)
if params.remove_edge_cells:
    labels, n_removed = filter_edge_cells(labels, params.edge_margin)
    if n_removed:
        console.print(f"  [dim]Removed {n_removed} edge cell(s)[/dim]")
```

**Record in segmentation run parameters:** Store `edge_margin` value in the segmentation run's parameters JSON for reproducibility.

### Feature 2: Gaussian Smoothing Before Thresholding

Add `gaussian_sigma` parameter to `ThresholdEngine` methods. Apply `scipy.ndimage.gaussian_filter()` to the image before computing the threshold value.

**Files to modify:**

| File | Change |
|------|--------|
| `src/percell3/measure/thresholding.py:41` | Add `gaussian_sigma: float \| None = None` to `threshold_fov()` |
| `src/percell3/measure/thresholding.py:73-76` | Apply `gaussian_filter()` between image read and threshold compute |
| `src/percell3/measure/thresholding.py:85-88` | Record `gaussian_sigma` in threshold run parameters |
| `src/percell3/measure/thresholding.py:106` | Add `gaussian_sigma` to `threshold_group()` |
| `src/percell3/measure/thresholding.py:145` | Apply smoothing to group_image before mask creation |
| `src/percell3/measure/threshold_viewer.py:32` | Add `gaussian_sigma` to `compute_masked_otsu()` |
| `src/percell3/cli/menu.py` (threshold handler) | Add sigma prompt to interactive threshold menu |

**Implementation — `threshold_fov()` change:**

```python
def threshold_fov(
    self,
    store: ExperimentStore,
    fov_id: int,
    channel: str,
    method: str = "otsu",
    manual_value: float | None = None,
    gaussian_sigma: float | None = None,  # NEW
) -> ...:
    image = store.read_image_numpy(fov_id, channel)

    # NEW: Apply Gaussian smoothing
    if gaussian_sigma is not None and gaussian_sigma > 0:
        from scipy.ndimage import gaussian_filter
        image = gaussian_filter(image.astype(np.float64), sigma=gaussian_sigma)

    threshold_value = self._compute_threshold(image, method, manual_value)
    ...
```

**Note:** The threshold is computed on the smoothed image AND the mask is created from the smoothed image. This matches PerCell's behavior (PerCell thresholded the blurred image).

### Feature 3: Cell Group Labels in All Exports

Add group tag columns to all export formats. The `CellGrouper` already creates tags like `group:GFP:mean_intensity:g1` in the `cell_tags` table.

**Files to modify:**

| File | Change |
|------|--------|
| `src/percell3/core/queries.py` | Add `select_group_tags_for_cells(conn, cell_ids) -> dict[int, dict[str, str]]` |
| `src/percell3/core/experiment_store.py` | Add `get_cell_group_tags(cell_ids) -> dict` |
| `src/percell3/core/experiment_store.py:520` | Merge group columns in `get_measurement_pivot()` |
| `src/percell3/core/experiment_store.py:898` | Add group column in `export_prism_csv()` |
| `src/percell3/core/experiment_store.py:999` | Add group column in `export_particles_csv()` |

**New SQL query — `queries.py`:**

```python
def select_group_tags_for_cells(
    conn: sqlite3.Connection,
    cell_ids: list[int],
) -> list[tuple[int, str]]:
    """Return (cell_id, tag_name) pairs for group tags."""
    if not cell_ids:
        return []
    placeholders = ",".join("?" * len(cell_ids))
    rows = conn.execute(
        f"""
        SELECT ct.cell_id, t.name
        FROM cell_tags ct
        JOIN tags t ON ct.tag_id = t.id
        WHERE t.name LIKE 'group:%'
          AND ct.cell_id IN ({placeholders})
        ORDER BY ct.cell_id
        """,
        cell_ids,
    ).fetchall()
    return rows
```

**Column naming for multiple groupings:**

A cell might have tags from different grouping runs (e.g., `group:GFP:mean_intensity:g1` and `group:RFP:area_um2:g2`). Each unique `(channel, metric)` combination gets its own column:

- Tag `group:GFP:mean_intensity:g1` → column `group_GFP_mean_intensity` with value `g1`
- Tag `group:RFP:area_um2:g2` → column `group_RFP_area_um2` with value `g2`

If only one grouping exists, use a single `group` column for simplicity.

**Cells without group tags:** Empty string in the column.

## Acceptance Criteria

### Feature 1: Edge Cell Removal
- [x] `filter_edge_cells()` function in `segment/label_processor.py`
- [x] `remove_edge_cells` and `edge_margin` parameters on `SegmentationParams`
- [x] Segmentation engine calls filter when `remove_edge_cells=True`
- [x] Filtered labels written to zarr (edge cells not in label image)
- [x] Edge cells do not appear in database
- [x] Console output shows count of removed cells
- [x] `edge_margin` recorded in segmentation run parameters
- [x] `--edge-margin` CLI flag on `percell3 segment`
- [x] Interactive menu offers edge removal option
- [x] Tests: normal filtering, margin=0, large margin, all-cells-removed, re-segmentation

### Feature 2: Gaussian Smoothing
- [x] `gaussian_sigma` parameter on `threshold_fov()`, `threshold_group()`, `compute_masked_otsu()`
- [x] `scipy.ndimage.gaussian_filter` applied when sigma is set
- [x] No smoothing when `gaussian_sigma` is `None` or `0` (preserves current behavior)
- [x] `gaussian_sigma` recorded in threshold run parameters
- [x] Interactive menu prompts for sigma (with default None)
- [x] Tests: sigma=None (no change), sigma=1.7 (different threshold value), sigma=0 (no change)

### Feature 3: Group Labels in Exports
- [x] `select_group_tags_for_cells()` query in `queries.py`
- [x] `get_cell_group_tags()` method on `ExperimentStore`
- [x] Group column(s) in wide CSV export (`get_measurement_pivot`)
- [x] Group column(s) in Prism CSV export (`export_prism_csv`)
- [x] Group column(s) in particle CSV export (`export_particles_csv`)
- [x] Multiple groupings produce separate columns (`group_{channel}_{metric}`)
- [x] Cells without group tags have empty string in column
- [x] Tests: single grouping, multiple groupings, no grouping, export with/without groups

## Implementation Phases

### Phase 1: Edge Cell Removal
1. Add `filter_edge_cells()` to `label_processor.py` with tests
2. Add params to `SegmentationParams` and wire into `_engine.py`
3. Add CLI flag and menu option
4. Test end-to-end

### Phase 2: Gaussian Smoothing
1. Add `gaussian_sigma` parameter to `threshold_fov()` and `threshold_group()` with tests
2. Update `compute_masked_otsu()` in `threshold_viewer.py`
3. Add menu prompt and CLI option
4. Test end-to-end

### Phase 3: Group Labels in Exports
1. Add `select_group_tags_for_cells()` query and `get_cell_group_tags()` store method with tests
2. Merge group columns into `get_measurement_pivot()`
3. Add group column to `export_prism_csv()`
4. Add group column to `export_particles_csv()`
5. Test all export formats with single/multiple/no groupings

## Dependencies & Risks

- **scikit-image** `clear_border` is available but doesn't support configurable margin — custom implementation needed (straightforward)
- **scipy.ndimage.gaussian_filter** already used in other parts of the codebase (surface mesh plugin)
- **Measurement CLI handler missing** — `_measure_channels` is not implemented, which blocks thresholding from the interactive menu. Not in scope for this plan but noted as a related gap.
- **Empty cell_ids list in SQL** — must guard against `IN ()` per learnings from `docs/solutions/security-issues/core-module-p1-security-correctness-fixes.md`

## References

- Brainstorm: `docs/brainstorms/2026-02-25-missing-percell-processing-steps-brainstorm.md`
- PerCell edge filter: `percell/macros/filter_edge_rois.ijm`
- PerCell Gaussian smoothing: `percell/macros/threshold_grouped_cells.ijm:198`
- Segmentation engine: `src/percell3/segment/_engine.py:123-186`
- Label processor: `src/percell3/segment/label_processor.py:13-84`
- Threshold engine: `src/percell3/measure/thresholding.py:41-206`
- Cell grouper tags: `src/percell3/measure/cell_grouper.py:218`
- Wide CSV export: `src/percell3/core/experiment_store.py:479-531`
- Prism export: `src/percell3/core/experiment_store.py:821-972`
- Particle export: `src/percell3/core/experiment_store.py:979-1044`
- Security learnings (empty SQL guard): `docs/solutions/security-issues/core-module-p1-security-correctness-fixes.md`
