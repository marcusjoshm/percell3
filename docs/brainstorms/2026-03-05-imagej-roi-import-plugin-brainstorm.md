---
title: "ImageJ ROI Import as Segmentation Layers"
date: 2026-03-05
type: feat
---

# ImageJ ROI Import as Segmentation Layers

## What We're Building

A CLI menu action that imports ImageJ ROI .zip files (polygon/freehand outlines) as cellular segmentation layers. Each .zip file contains ROIs for one FOV. The user selects target FOVs from a list during import.

### Core Flow

1. User selects "Import ImageJ ROIs" from the Edit menu
2. Chooses **single file** or **folder** mode
3. For each .zip file:
   - Selects a target FOV from the experiment's FOV list
   - Chooses naming: auto (from .zip filename) or manual (type a name)
4. ROIs are rendered into a label image matching the FOV dimensions
5. Existing `RoiImporter.import_labels()` handles storage, cell extraction, config assignment, and auto-measurement

### What It Produces

- A new `cellular` segmentation entity per .zip file
- Label image stored in Zarr (pixel value = cell ID, 0 = background)
- Cells extracted with centroids, bounding boxes, areas
- Auto-configured in `fov_config` for the target FOV
- Auto-measured on all channels

## Why This Approach

### Reuse existing infrastructure

The heavy lifting is already built:
- `RoiImporter.import_labels()` in `segment/roi_import.py` — stores labels, extracts cells, triggers auto-config and auto-measurement
- `store_labels_and_cells()` — writes Zarr, creates cell records
- `extract_cells()` in `label_processor.py` — regionprops-based cell extraction
- `_auto_config_segmentation()` — assigns segmentation to FOV config
- `on_segmentation_created()` — triggers auto-measurement

The only new code needed:
1. **ROI .zip reader** — use `roifile` package to parse ImageJ ROI format
2. **Polygon-to-label renderer** — use `skimage.draw.polygon` to rasterize ROI outlines into a label image
3. **CLI menu flow** — file/folder selection, FOV picker, naming

### Why not a full AnalysisPlugin?

Import operations are not analysis — they don't process existing data, they bring in new data. The existing import flows (LIF, TIFF, Cellpose _seg.npy) are all CLI menu actions, not plugins. Following this pattern is consistent and simpler.

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| ROI format | Polygon/freehand outlines only | User's data is cell outlines drawn in ImageJ |
| Zip-to-FOV mapping | One .zip = one FOV | User confirmed this is their workflow |
| File selection | Single file + batch folder | Flexibility for one-off and bulk imports |
| Batch matching | Always manual (no auto-match) | User wants explicit control over FOV assignment |
| Naming | Auto (from filename) or manual (user types) | Two options presented at import time |
| UI location | CLI Edit menu | Consistent with existing import operations |
| Architecture | CLI menu action, not AnalysisPlugin | Import ≠ analysis; matches existing patterns |
| ROI reader library | `roifile` Python package | Pure-Python, reads ImageJ ROI .zip format |
| Label rendering | `skimage.draw.polygon` | Already a dependency, handles polygon rasterization |
| Segmentation type | `cellular` with `model_name="imagej"` | Matches existing `import_labels()` convention |

## Resolved Questions

- **ROI types?** Polygon/freehand outlines (cell boundaries)
- **Zip-to-FOV relationship?** One zip per FOV
- **File input?** Both single file and folder of zips
- **Batch matching?** Always manual assignment
- **UI location?** CLI menu (Edit submenu)
- **Naming?** Auto from filename + manual entry option
- **Architecture?** CLI menu action, not plugin

## Open Questions

None — all design questions resolved during brainstorming.
