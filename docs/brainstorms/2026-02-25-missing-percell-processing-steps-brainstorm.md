---
title: "Missing PerCell Processing Steps — Edge Cell Removal, Gaussian Smoothing, Group Export"
type: feat
date: 2026-02-25
status: decided
---

# Missing PerCell Processing Steps Brainstorm

## What We're Building

Three processing features from the original PerCell that are missing in PerCell 3, plus an export enhancement for cell grouping:

1. **Edge cell removal** — Remove partial cells whose bounding box touches the image border after segmentation, before they enter the database.
2. **Gaussian smoothing before thresholding** — Optional Gaussian blur applied to the image before Otsu or other threshold methods, with a configurable sigma parameter.
3. **Cell group labels in all exports** — Include the GMM-based cell group assignments (already computed by `CellGrouper`) as a column in all export formats: wide CSV, per-cell metrics, particle metrics, and Prism format.

**Deferred:** Cell tracking across timepoints was considered but deferred to a separate brainstorm due to complexity.

## Why These Changes

### Edge Cell Removal
The original PerCell ran `filter_edge_rois.ijm` (at `/percell/macros/filter_edge_rois.ijm`) as step 4 of its workflow, removing any ROI whose bounding box was within a configurable margin of the image edge. This prevents partial cells from skewing per-cell measurements (integrated intensity, area, circularity are all wrong for clipped cells). PerCell 3 has no equivalent — all cells from Cellpose output are kept, including those on borders.

### Gaussian Smoothing
PerCell applied `Gaussian Blur sigma=1.70` and `Enhance Contrast saturated=0.01` before Otsu thresholding in both semi-auto and full-auto macros (`threshold_grouped_cells.ijm`, `full_auto_threshold_grouped_cells.ijm`). This reduces noise and improves thresholding accuracy. PerCell 3's `ThresholdEngine` applies thresholds directly to raw pixel values with no preprocessing.

### Cell Group Export
PerCell 3's `CellGrouper` already computes GMM-based intensity groups and stores them as cell tags (e.g., `group:GFP:mean_intensity:g1`). However, none of the export functions currently include these tags in their output. Scientists need group labels in their exports to analyze per-group statistics in GraphPad Prism and other tools.

## Key Decisions

### 1. Edge Cell Removal — Post-Segmentation Filter

**Decision:** Remove edge cells from the label image immediately after segmentation, before cell properties are extracted and inserted into the database. Edge cells never enter the DB.

**Implementation location:** New function in `segment/label_processor.py` (or a small `segment/edge_filter.py`), called by `_engine.py` between Cellpose output and `extract_cells()`.

**Parameters:**
- `edge_margin` (int, default 0): Number of pixels from the image border. A cell is removed if any part of its bounding box is within this margin. Default 0 means only cells directly touching the edge are removed.
- Enabled/disabled via a boolean flag in segmentation parameters.

**Algorithm (from PerCell, adapted for label images):**
1. Get image dimensions (H, W) from the label array shape
2. For each cell (via `regionprops`), get bounding box `(min_row, min_col, max_row, max_col)`
3. If `min_row <= edge_margin` OR `min_col <= edge_margin` OR `max_row >= H - edge_margin` OR `max_col >= W - edge_margin`, set those pixels to 0 in the label image
4. Return the filtered label image and count of removed cells

**PerCell reference:** `percell/macros/filter_edge_rois.ijm` (lines 1-279), orchestrated by `imagej_tasks.py:filter_edge_rois` (lines 106-214).

### 2. Gaussian Smoothing — Configurable Sigma on ThresholdEngine

**Decision:** Add an optional `gaussian_sigma` parameter to `ThresholdEngine.threshold_fov()` and `threshold_group()`. When set, apply `scipy.ndimage.gaussian_filter(image, sigma)` before computing the threshold. Default to `None` (no smoothing) to preserve current behavior.

**Implementation location:** `measure/thresholding.py`, within the existing `ThresholdEngine` class.

**Parameters:**
- `gaussian_sigma` (float | None, default None): Standard deviation for Gaussian kernel. Set to 1.7 to match PerCell's behavior. `None` or `0` skips smoothing.

**Behavior:**
- Smoothing is applied only for threshold computation — the raw image data is not modified.
- The smoothed image is used to compute the threshold value, then the threshold is applied to the original (unsmoothed) image to create the binary mask. This preserves sharp boundaries in the mask.
- Alternatively: apply threshold to the smoothed image. **Decision: apply to smoothed image** to match PerCell's behavior (PerCell thresholded the blurred image).

**PerCell reference:** `percell/macros/threshold_grouped_cells.ijm` (line 198: `run("Gaussian Blur...", "sigma=1.70")`).

### 3. Cell Group Labels in All Exports

**Decision:** Add a `group` column to all export outputs when cell grouping has been performed. The column contains the group label (e.g., `g1`, `g2`, `g3`) for each cell.

**Implementation locations:**
- `core/store.py` — `export_csv()` method needs to join cell tags matching `group:*` pattern
- `cli/export_prism.py` — Prism export needs group column as an additional variable
- Particle export (wherever particle CSV is written) — include parent cell's group

**Column format:**
- Column name: `group` (or `group_{channel}_{metric}` if multiple groupings exist)
- Values: `g1`, `g2`, `g3`, etc. (from the tag `group:CH:metric:gN`)
- Cells without a group assignment get an empty string or `ungrouped`

**What's already in place:**
- `CellGrouper` (`measure/cell_grouper.py`) creates tags like `group:GFP:mean_intensity:g1`
- Tags are stored in the `cell_tags` SQLite table
- `store.get_cell_tags(cell_id)` retrieves tags
- Export functions don't currently query tags

## Complete Gap Analysis: PerCell vs PerCell 3

For reference, here is the full inventory of PerCell features and their PerCell 3 status:

| PerCell Feature | PerCell 3 Status | Action |
|----------------|-----------------|--------|
| Edge cell removal | **Missing** | Implement (this brainstorm) |
| Cell tracking | **Missing** | Deferred to separate brainstorm |
| Gaussian smoothing before threshold | **Missing** | Implement (this brainstorm) |
| Cell group labels in exports | **Missing** | Implement (this brainstorm) |
| Cell grouping (GMM) | Implemented (`CellGrouper`) | No action needed |
| Image binning/downsampling | Not needed | Cellpose handles large images natively |
| ROI resizing (binned → full-res) | Not needed | No binning = no resizing |
| ROI duplication for channels | Not needed | Labels apply to all channels in PerCell 3 |
| Cell extraction (individual crops) | Not needed | PerCell 3 measures in-place via bbox |
| Otsu thresholding | Implemented (`ThresholdEngine`) | No action needed |
| Particle analysis | Implemented (`ParticleAnalyzer`) | No action needed |
| Mask combination | Not needed | PerCell 3 thresholds per-FOV, not per-group |
| P-body / SG analysis | Not implemented | Could be a plugin; not in scope |
| Image stitching | Not implemented | Preprocessing utility; not in scope |
| Z-projection | Implemented (`io/transforms.py`) | No action needed |
| Cell classification | **Stub only** | Not in scope for this brainstorm |
| Cellpose segmentation | Implemented | No action needed |
| CSV export | Implemented | Enhancement needed (group column) |
| Prism export | Implemented | Enhancement needed (group column) |
| Napari viewer | Implemented | No action needed |
| Local background subtraction | Implemented (plugin) | No action needed |

## Resolved Questions

1. **Edge cell removal approach?** — Post-segmentation filter. Remove from label image before DB insertion.
2. **Cell tracking?** — Deferred to a separate brainstorm.
3. **Gaussian sigma configurable or fixed?** — Configurable with None as default (no smoothing). Set to 1.7 to match PerCell.
4. **Smooth then threshold, or threshold the original?** — Apply threshold to the smoothed image (match PerCell behavior).
5. **Group export scope?** — Add group column to all export formats (wide CSV, per-cell, particle, Prism).
6. **Multiple groupings?** — If multiple groupings exist (different channels/metrics), use column name `group_{channel}_{metric}`.
