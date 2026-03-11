---
title: "Napari Viewer Integration & Pixel Size Metadata"
type: feat
status: completed
date: 2026-03-10
---

# Napari Viewer Integration & Pixel Size Metadata

Add three features to PerCell4: (1) full interactive napari viewer with FOV browsing, ROI editing, and re-segmentation; (2) interactive threshold viewer with live preview; (3) per-FOV pixel_size_um metadata extracted from import files, enabling calibrated area measurements and physical-unit display.

**User decisions:**
- Full interactive viewer (draw + delete ROIs, re-run Cellpose from napari)
- Per-FOV pixel size (not per-experiment or per-channel — supports mixed-magnification)
- Import-only pixel size detection (auto-extract from TIFF/LIF metadata, no manual override UI)

---

## Dependencies

- napari (optional, guarded behind `try: import napari`)
- qtpy (Qt compatibility layer — never import PyQt5/PySide2 directly)
- cellpose (already optional in percell4)
- tifffile (already a dependency)

---

## Step 1: Pixel Size Infrastructure

**Gate target: independent of viewer, can be done first**

Add per-FOV pixel_size_um support through the full stack.

### 1a. Schema + Migration

- [x] Add `pixel_size_um REAL` column to `fovs` table in `schema.py`
- [x] Add schema migration `5.0.0->5.1.0` in `migration.py`: `ALTER TABLE fovs ADD COLUMN pixel_size_um REAL`
- [x] Update `SCHEMA_VERSION` to `"5.1.0"` in `migration.py`
- [x] Update FovInfo model in `models.py`: add `pixel_size_um: float | None = None` field

### 1b. TIFF Metadata Extraction

- [x] Port `_extract_pixel_size()` from percell3's `src/percell3/io/tiff.py` to percell4's `src/percell4/io/tiff.py`
  - Check OME-XML `PhysicalSizeX` + unit conversion (um, nm, mm, cm)
  - Check ImageJ metadata `spacing` key
  - Check TIFF resolution tags `XResolution` + `ResolutionUnit`
- [x] Add `read_tiff_metadata(path) -> dict` function returning `{'shape', 'dtype', 'pixel_size_um'}`
- [x] Update `FileInfo` in `scanner.py`: add `pixel_size_um: float | None = None`
- [x] Update `scan_directory()` to call `read_tiff_metadata()` and populate `pixel_size_um`

### 1c. Import Pipeline

- [x] Update `ImportEngine.import_images()` to accept and propagate pixel_size_um
- [x] Extract pixel_size_um from `FileInfo` during import
- [x] Pass pixel_size_um to `insert_fov()` call in ExperimentDB
- [x] Update `ExperimentDB.insert_fov()` to accept and store pixel_size_um

### 1d. Zarr Physical Scale

- [x] Update `LayerStore.write_image_channels()` to include physical scale in OME-NGFF metadata when pixel_size_um is available:
  ```python
  "axes": [
      {"name": "y", "type": "space", "unit": "micrometer"},
      {"name": "x", "type": "space", "unit": "micrometer"},
  ],
  "coordinateTransformations": [
      [{"type": "scale", "scale": [pixel_size_um, pixel_size_um]}]
  ]
  ```
- [x] Read pixel_size_um from zarr metadata in `read_image_channel()` if available (fallback for FOVs imported before schema migration)

### 1e. Calibrated Area Measurements

- [x] Update ROI area calculation in `measurer.py` to compute `area_um2 = area_pixels * (pixel_size_um ** 2)` when pixel_size_um is available
- [x] Add `area_um2` to measurement output (metric name: `area_um2`)
- [x] Update `export_measurements_csv()` to include `area_um2` column when pixel_size_um is known
- [x] Update `condensate_partitioning_ratio.py`: replace always-NaN `_um2` fields with real values when pixel_size_um is available, remove fields when not

### 1f. Tests

- [x] `test_tiff_metadata.py`: test pixel size extraction from OME-XML, ImageJ, TIFF tags, missing metadata
- [x] `test_schema_migration.py`: test 5.0.0 -> 5.1.0 migration adds pixel_size_um column
- [x] `test_import_pixel_size.py`: test pixel_size_um flows from TIFF -> scanner -> import -> DB -> model
- [x] `test_area_um2.py`: test calibrated area calculation with known pixel size

---

## Step 2: Viewer Core — Launch, Load, Browse

**Port percell3's viewer infrastructure to percell4.**

### 2a. Viewer Module Structure

- [x] Create `src/percell4/viewer/` package
- [x] Create `__init__.py` with `launch_viewer()` public API, napari availability guard
- [x] Create `_viewer.py` — orchestration: create viewer, load layers, register widgets, block on `napari.run()`, handle save-back

### 2b. Image & Label Loading

- [x] `_load_channel_layers(viewer, store, fov_id)` — load all channels as napari Image layers with `blending="additive"`
  - Use `store.layers.read_image_channel(fov_hex, idx)` for lazy dask arrays
  - Apply channel colormap from `ch["color"]` field
  - Pass `scale=(pixel_size_um, pixel_size_um)` when available
- [x] `_load_label_layer(viewer, store, fov_id)` — load active segmentation labels
  - Get active assignment via `store.db.get_active_assignments(fov_id)`
  - Load via `store.layers.read_labels(seg_set_hex, fov_hex)`
  - Pass same `scale` as images
  - Set `opacity=0.5`, name by segmentation set
- [x] `_load_mask_layers(viewer, store, fov_id)` — load active threshold masks
  - Load via `store.layers.read_mask(mask_hex)`
  - Display as Image layers with `colormap="magenta"`, `opacity=0.4`, `visible=False`

### 2c. FOV Browser Widget

- [x] Create `src/percell4/viewer/fov_browser_widget.py`
- [x] QWidget with QListWidget listing all FOVs (auto_name + status + condition)
- [x] Click-to-load: clears current layers, loads selected FOV
- [x] Color-code by status (green=measured, yellow=segmented, gray=imported, red=error)
- [x] Show current FOV info panel (name, condition, status, pixel_size_um, channel count)

### 2d. Save-on-Close

- [x] Track original label array hash (SHA-256) at load time
- [x] On viewer close: compare hash, if changed → `save_edited_labels()`
- [x] `save_edited_labels()`: extract ROIs from edited labels, create new segmentation run with `model_name="napari_edit"`, re-measure affected FOV

### 2e. CLI & Menu Integration

- [x] Add `view` command to CLI (`main.py`): `percell4 view --fov <name_or_uuid>`
- [x] Add viewer handler to `menu_handlers/` — select FOV from table, launch viewer
- [x] Guard: `if not NAPARI_AVAILABLE: print_error("napari required: pip install napari[all]")`

### 2f. Tests

- [x] `test_viewer_init.py`: test napari guard, test launch_viewer exists
- [x] `test_fov_browser.py`: test widget creation with mock store (unit test, no display)
- [x] `test_save_edited_labels.py`: test label change detection and save-back logic

---

## Step 3: ROI Editing Widgets

**Port percell3's edit and cellpose widgets.**

### 3a. Edit Widget

- [x] Create `src/percell4/viewer/edit_widget.py`
- [x] Delete Cell: pick mode → click on label → fill with 0
- [x] Draw Cell: add Shapes layer in `add_polygon` mode → rasterize with `skimage.draw.polygon` → assign new label ID
- [x] Both operations update the labels layer immediately (`labels_layer.refresh()`)
- [x] QWidget with Delete/Draw buttons, undo via napari's built-in undo

### 3b. Cellpose Re-Segmentation Widget

- [x] Create `src/percell4/viewer/cellpose_widget.py`
- [x] QWidget with: model selector (cyto3, nuclei, etc.), diameter spinner, channel selector, flow_threshold slider
- [x] "Run Segmentation" button → `@thread_worker` async execution
- [x] On completion: update labels layer, trigger save-back prompt
- [x] Creates new segmentation run with `model_name="cellpose"` and JSON params

### 3c. Edge Removal Widget

- [x] Create `src/percell4/viewer/edge_removal_widget.py`
- [x] Preview edge cells highlighted (different color)
- [x] Min area filter with slider
- [x] Apply button → updates labels, marks removed cells

### 3d. Tests

- [x] `test_edit_widget.py`: test widget creation, test rasterize polygon logic
- [x] `test_cellpose_widget.py`: test widget creation with mock segmenter

---

## Step 4: Interactive Threshold Viewer

**napari-based threshold adjustment with live preview.**

### 4a. Threshold Widget

- [x] Create `src/percell4/viewer/threshold_widget.py`
- [x] QWidget with: channel selector, threshold value slider (range from channel min/max), method selector (manual, otsu, etc.)
- [x] Live preview: as slider moves, update a mask overlay layer in real-time showing pixels above/below threshold
- [x] Apply button: create threshold mask via `compute_threshold()` + `create_threshold_mask()`, assign to FOV
- [x] Show particle count and mean particle area as user adjusts threshold

### 4b. Group Threshold Widget

- [x] Create `src/percell4/viewer/group_threshold_widget.py`
- [x] For intensity groups: show grouped FOVs, apply same threshold across group
- [x] Preview on current FOV, apply to all FOVs in group on confirm

### 4c. CLI Integration

- [x] Update `threshold` CLI command to launch napari threshold viewer when interactive
- [x] Update threshold menu handler to launch widget

### 4d. Tests

- [x] `test_threshold_widget.py`: test threshold preview logic (mask generation from value)
- [x] `test_group_threshold.py`: test group application logic

---

## Step 5: Measurement Display & Polish

### 5a. Measurement Overlay

- [x] Add measurement display option: color-code ROI labels by measurement value (e.g., mean intensity → heatmap colormap)
- [x] Add Points layer with measurement text annotations at ROI centroids (optional, toggle-able)

### 5b. Scale Bar

- [x] When pixel_size_um is available, napari automatically shows scale bar in physical units via the `scale` parameter
- [x] Verify scale bar displays correctly with `viewer.scale_bar.visible = True`

### 5c. Status Bar Info

- [x] Show FOV name, condition, pixel_size_um, and ROI count in viewer title bar
- [x] Update on FOV switch

### 5d. Tests

- [x] `test_measurement_overlay.py`: test color-coding logic with mock measurements

---

## Acceptance Criteria

1. `percell4 view` opens napari with all channels, labels, and masks for a selected FOV
2. FOV browser widget allows switching between FOVs without restarting napari
3. ROI editing (draw polygon, delete cell) persists to database on viewer close
4. Cellpose re-segmentation runs from napari with parameter adjustment
5. Threshold slider shows live mask preview, particle count updates in real-time
6. pixel_size_um extracted from TIFF metadata during import and stored per-FOV
7. Calibrated area_um2 measurements appear in CSV exports when pixel_size_um is known
8. All napari layers display in physical units (micrometer) when pixel_size_um is available
9. napari is optional — all non-viewer commands work without it installed
10. SQLite operations always on main thread; only computation (Cellpose, thresholding) in background threads

---

## Implementation Notes

### Patterns from percell3 viewer (port, don't reinvent)
- Widget convention: QWidget subclass with `_viewer`, `_store`, `_fov_id` instance vars
- Qt via `qtpy` only — never PyQt5/PySide2 directly
- `napari.run()` blocking model with save-on-close
- `@thread_worker` for async computation, results saved on main thread
- Change detection: SHA-256 hash of label array bytes

### Key differences from percell3
- UUID hex strings in all LayerStore paths (not integer IDs)
- Channel index lookup via `find_channel_index()` helper
- Active assignments query for determining which labels/masks to load
- ROI insert via `store.insert_roi_checked()` with cell identity enforcement
- Hexagonal boundary: viewer module imports `experiment_store` only, never `experiment_db` or `layer_store` directly

### Architecture boundary
The viewer module at `src/percell4/viewer/` is a new top-level module, NOT inside `segment/`. It depends on `core.experiment_store` only. The boundary test in `test_boundary.py` must be updated to include `viewer` in the EXTERNAL_MODULES list.

---

## Sources

- Research files: `.workflows/plan-research/napari-viewer-pixel-size/agents/`
- PerCell3 viewer reference: `src/percell3/segment/viewer/` (7 dock widgets, ~2000 lines)
- PerCell3 pixel size: `src/percell3/io/tiff.py` (`_extract_pixel_size()`)
- Viewer code review findings: `docs/solutions/architecture-decisions/viewer-module-code-review-findings.md`
- Viewer architecture plan: `docs/archive/plans/2026-02-16-feat-segment-module-3b-napari-viewer-plan.md`
