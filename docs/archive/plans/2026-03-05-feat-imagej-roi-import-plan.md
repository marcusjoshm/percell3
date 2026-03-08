---
title: "feat: Import ImageJ ROI .zip files as segmentation layers"
type: feat
date: 2026-03-05
---

# feat: Import ImageJ ROI .zip Files as Segmentation Layers

## Overview

Add a CLI menu action that imports ImageJ ROI .zip files (polygon/freehand outlines) as cellular segmentation layers. Each .zip contains ROIs for one FOV. The user selects target FOVs from a list and chooses naming (auto from filename or manual). Supports single-file and batch-folder modes.

## Problem Statement / Motivation

Users have libraries of cell outlines drawn in ImageJ and saved as ROI .zip files. Currently there is no way to bring these into PerCell 3 as segmentation layers. The only segmentation import paths are Cellpose `_seg.npy` files (via `RoiImporter.import_cellpose_seg()`) and direct label arrays (via `RoiImporter.import_labels()`). Users must manually convert ROIs to label images outside PerCell, which is error-prone and breaks the workflow.

## Proposed Solution

Add a new module `segment/imagej_roi_reader.py` that reads ImageJ ROI .zip files using the `roifile` package and renders polygon outlines to a label image using `skimage.draw.polygon`. Wire this into the CLI Edit menu as "Import ImageJ ROIs" with single-file and batch-folder modes. Reuse existing `store_labels_and_cells()` for storage, cell extraction, and auto-measurement.

## Technical Approach

### Architecture

```
CLI (menu.py)
  └── _import_imagej_rois(state)
        ├── Single file mode
        │     └── _import_single_roi_zip(store, zip_path, fov_id, seg_name)
        └── Folder mode
              └── Loop: _import_single_roi_zip() per .zip file

segment/imagej_roi_reader.py
  └── rois_to_labels(zip_path, image_shape) -> np.ndarray
        ├── roifile.roiread(zip_path) → list[ImagejRoi]
        ├── Filter to polygon/freehand/traced ROI types
        ├── skimage.draw.polygon(row, col, shape) per ROI
        └── Return int32 label image (0 = background)
```

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| ROI reader library | `roifile` (optional dependency) | Pure Python, reads ImageJ ROI format, by same author as `tifffile` |
| Label rendering | `skimage.draw.polygon` with `shape=` param | Auto-clips out-of-bounds coordinates; already a dependency |
| Overlap strategy | Last-ROI-wins (later ROI overwrites earlier pixels) | Standard rasterization behavior; matches ImageJ's own rendering |
| Unsupported ROI types | Skip with warning count | .zips may contain points/lines alongside polygons |
| Empty result (0 ROIs) | Abort with message, do not create segmentation | Almost certainly a user error |
| FOV without dimensions | Abort with clear error | Cannot render labels without target dimensions |
| Naming | User chooses: auto (from .zip filename stem) or manual (type name) | Passed directly to `add_segmentation()` as the name |
| Menu placement | Edit menu (item 10: "Import ImageJ ROIs") | Groups with segmentation management; Import menu is for raw images |
| Dependency management | Optional extra, lazy import with helpful error | Matches `cellpose` pattern |
| Batch error handling | Continue on error, collect warnings, show summary | Matches `SegmentationEngine.run()` pattern |
| Folder scan | Non-recursive (top-level .zip files only) | Typical ImageJ workflow |
| Re-segmentation warning | Show warning when FOV already has cellular seg | Matches Cellpose segmentation flow |
| File picker filter | `("ImageJ ROI files", "*.zip")` | Prevent accidental non-.zip selection |
| Coordinate swap | `row = coords[:, 1]`, `col = coords[:, 0]` | roifile returns (x,y), skimage expects (row,col) |

### Implementation Phases

#### Phase 1: ROI Reader Module

- [x] Add `roifile` to `pyproject.toml` as optional dependency (`imagej` extra)
- [x] Create `src/percell3/segment/imagej_roi_reader.py`
  - [x] `rois_to_labels(zip_path: Path, image_shape: tuple[int, int]) -> np.ndarray`
    - [x] Lazy-import `roifile` with clear error if not installed
    - [x] Read .zip via `roifile.roiread()`
    - [x] Filter to polygon/freehand/traced ROI types (`ROI_TYPE.POLYGON`, `FREEHAND`, `TRACED`)
    - [x] Skip unsupported types, count skipped
    - [x] Render each ROI to label image using `skimage.draw.polygon(row, col, shape=image_shape)`
    - [x] Swap coordinates: `row = coords[:, 1]`, `col = coords[:, 0]`
    - [x] Return int32 label image and metadata dict (roi_count, skipped_count, skipped_types)
  - [x] Handle edge cases: empty .zip, non-ImageJ .zip, ROIs with < 3 vertices

#### Phase 2: CLI Integration

- [x] Add `_import_imagej_rois(state)` to `menu.py`
  - [x] Mode selection: "Single .zip file" or "Folder of .zip files"
  - [x] **Single file flow:**
    - [x] File picker with .zip filter (via `_prompt_path` with `mode="file"`)
    - [x] FOV selection from numbered list (via `_select_fovs` or similar)
    - [x] Validate FOV has dimensions (width/height not None)
    - [x] Naming: auto (filename stem) or manual (user types)
    - [x] Preview: "Found N polygon ROIs (skipped M non-polygon). Import to FOV '{name}' as '{seg_name}'?"
    - [x] Re-segmentation warning if FOV already has cellular seg
    - [x] Call `rois_to_labels()` → `add_segmentation()` → `store_labels_and_cells()` → `on_segmentation_created()`
    - [x] Display result: "Imported {N} cells from {filename}"
  - [x] **Folder flow:**
    - [x] Folder picker (via `_prompt_path` with `mode="dir"`)
    - [x] Discover .zip files (non-recursive `glob("*.zip")`)
    - [x] For each .zip: FOV selection + naming (same as single-file sub-flow)
    - [x] Continue-on-error: collect warnings for failed files
    - [x] Display batch summary: "Imported N/M files. Warnings: ..."
- [x] Add menu item to Edit menu: `MenuItem("10", "Import ImageJ ROIs", "Import ImageJ ROI .zip files as segmentations", _import_imagej_rois)`

#### Phase 3: Tests

- [x] Create `tests/test_segment/test_imagej_roi_reader.py`
  - [x] Test `rois_to_labels()` with synthetic polygon ROIs (create .zip programmatically with `roifile`)
  - [x] Test coordinate swap correctness (x,y → row,col)
  - [x] Test overlapping ROIs (last-wins behavior)
  - [x] Test out-of-bounds ROIs (clipped by `shape=`)
  - [x] Test filtering: polygon + freehand kept, lines/points skipped
  - [x] Test empty .zip (0 polygon ROIs)
  - [x] Test non-ImageJ .zip (graceful error)
  - [x] Test single ROI (degenerate case)
- [x] Integration test: .zip → labels → cells → measurements flow

## Acceptance Criteria

### Functional Requirements

- [x] User can import a single ImageJ ROI .zip file as a segmentation on a chosen FOV
- [x] User can batch-import a folder of .zip files, assigning each to a FOV
- [x] Polygon and freehand ROIs are rendered to a label image with unique cell IDs
- [x] Unsupported ROI types (lines, points, etc.) are skipped with a warning count
- [x] Auto-naming uses .zip filename stem; manual naming lets user type a name
- [x] Preview shows ROI count and confirms before import
- [x] Cells are extracted and auto-measured after import
- [x] FOV config is updated (via `_auto_config_segmentation`)
- [x] Warning shown when replacing an existing cellular segmentation

### Non-Functional Requirements

- [x] `roifile` is an optional dependency — clear error message if not installed
- [x] Out-of-bounds ROIs are clipped, not crashed
- [x] Empty or invalid .zip files produce user-friendly error messages
- [x] Batch mode continues on error, shows summary

## Technical Considerations

### Existing Code to Leverage

| Existing | Use For |
|----------|---------|
| `store_labels_and_cells()` (`roi_import.py:14`) | Write labels to Zarr, extract cells, update counts |
| `extract_cells()` (`label_processor.py:79`) | regionprops-based cell extraction from label image |
| `add_segmentation()` (`experiment_store.py:790`) | Create segmentation entity with custom name |
| `_auto_config_segmentation()` (`experiment_store.py:506`) | Auto-assign to FOV config |
| `on_segmentation_created()` (`auto_measure.py`) | Trigger auto-measurement |
| `_prompt_path()` (`menu.py:182`) | File/folder picker with tkinter dialog |
| `_select_items()` / FOV picker pattern (`menu.py`) | Multi-select from numbered list |

### New Code Needed

| New | Purpose |
|-----|---------|
| `segment/imagej_roi_reader.py` | Read .zip, render ROIs to label image |
| `_import_imagej_rois()` in `menu.py` | CLI menu flow |
| Tests in `test_imagej_roi_reader.py` | Unit + integration tests |

### Dependency: `roifile`

- Package: `roifile` by Christoph Gohlke (BSD-3-Clause)
- Requires: Python 3.11+, NumPy (both satisfied)
- Add to `pyproject.toml` as optional: `imagej = ["roifile"]`
- Lazy import pattern: `try: from roifile import roiread, ROI_TYPE except ImportError: raise ImportError("Install roifile: pip install percell3[imagej]")`

### Critical: Coordinate Swap

`roifile` `coordinates()` returns **(x, y)** pairs. `skimage.draw.polygon()` expects **(row, col)** which is **(y, x)**. Must swap:

```python
coords = roi.coordinates()  # shape (N, 2), columns [x, y]
row = coords[:, 1]  # y → row
col = coords[:, 0]  # x → col
rr, cc = draw_polygon(row, col, shape=image_shape)
```

### Known Limitation

`store_labels_and_cells()` calls `delete_cells_for_fov(fov_id)` which deletes ALL cells for the FOV, not scoped to a specific segmentation. This is a pre-existing issue (see `todos/142`). The ImageJ import inherits this behavior — importing ROIs for a FOV will delete cells from any other segmentation on that FOV.

## References

### Internal References

- ROI import: `src/percell3/segment/roi_import.py` — `store_labels_and_cells()` at line 14, `import_labels()` at line 58
- Label processor: `src/percell3/segment/label_processor.py` — `extract_cells()` at line 79
- ExperimentStore: `src/percell3/core/experiment_store.py` — `add_segmentation()` at line 790, `_auto_config_segmentation()` at line 506
- Auto-measurement: `src/percell3/measure/auto_measure.py` — `on_segmentation_created()`
- CLI menus: `src/percell3/cli/menu.py` — Edit menu at line 3085, `_prompt_path()` at line 182
- Brainstorm: `docs/brainstorms/2026-03-05-imagej-roi-import-plugin-brainstorm.md`

### External References

- `roifile` package: https://pypi.org/project/roifile/
- `roifile` source: https://github.com/cgohlke/roifile
- `skimage.draw.polygon`: https://scikit-image.org/docs/stable/api/skimage.draw.html#skimage.draw.polygon
