---
title: "feat: TIFF export for FOV images"
type: feat
date: 2026-02-27
branch: feat/split-halo-condensate-analysis
---

# feat: TIFF export for FOV images

## Overview

Add a general-purpose TIFF export feature that lets users export any FOV image (including derived FOVs from plugins) as `.tiff` files. Two access points: batch export from the CLI Data menu and a quick single-FOV export button in the napari viewer.

## Motivation

The split-halo-condensate plugin creates derived FOV images (`condensed_phase_*`, `dilute_phase_*`) stored in OME-Zarr. Users need TIFF exports for external analysis tools (FIJI/ImageJ), the 3D surface plot plugin, sharing with collaborators, and archival. Original imported images already have TIFFs on disk, but derived images exist only in zarr.

## Proposed Solution

### Core Export Function

Create a standalone `tiff_export.py` module in `percell3/core/` with the core logic:

```python
# src/percell3/core/tiff_export.py

def export_fov_as_tiff(
    store: ExperimentStore,
    fov_id: int,
    output_dir: Path,
    overwrite: bool = False,
) -> list[Path]:
    """Export all channels of a FOV as individual TIFF files.

    Returns list of written file paths.
    Raises FileExistsError if files exist and overwrite=False.
    """
```

**Behavior:**
- Read each channel via `store.read_image_numpy(fov_id, channel_name)` → 2D numpy array
- Write via `tifffile.imwrite(path, data, imagej=True, resolution=..., metadata=...)` preserving original dtype
- Include ImageJ-compatible pixel size metadata from `FovInfo.pixel_size_um`
- Filename: `{sanitized_fov_name}_{channel_name}.tiff`
- Sanitize filenames: replace spaces with `_`, strip parentheses
- Skip channels with missing image data (log warning, continue)

### CLI Data Menu Integration

Add "Export FOVs as TIFF" to the Data menu in `menu.py`:

```python
# In _data_menu():
MenuItem("4", "Export FOVs as TIFF", "Export images as TIFF files", _export_tiff),
```

**`_export_tiff(state)` handler flow:**
1. `store = state.require_experiment()`
2. `fovs = store.get_fovs()` — returns all FOVs (original + derived) in one list
3. Display FOV table via `_show_fov_status_table(fovs, ...)`
4. `selected = _select_fovs_from_table(fovs)` — multi-select by number or "all"
5. Check if output files exist → prompt "Files already exist. Overwrite? [y/n]"
6. Export with `make_progress()` progress bar
7. Print summary: "Exported N files to exports/tiff/"

### Napari Viewer Button

Add a small "Export" dock widget with a single button:

```python
# src/percell3/segment/viewer/tiff_export_widget.py

class TiffExportWidget:
    def __init__(self, viewer, store, fov_id, channel_names):
        self.widget = QWidget()
        # QPushButton "Export FOV as TIFF"
        # On click: call export_fov_as_tiff(), show status in napari
```

Register in `_viewer.py:_launch()` alongside existing dock widgets.

**On click behavior:**
- Re-read from ExperimentStore (not napari layer data) — guarantees original data fidelity
- Write to `exports/tiff/` (same as CLI)
- Overwrite without prompting (viewer context = quick export, user expects it)
- Show napari status bar message: "Exported 3 TIFFs to exports/tiff/"

## Technical Details

### File Naming

```
{sanitized_fov_display_name}_{channel_name}.tiff
```

Sanitization: `name.replace(" ", "_").replace("(", "").replace(")", "")`

Examples:
- `FOV_001_DAPI.tiff`
- `condensed_phase_FOV_001_GFP.tiff`
- `dilute_phase_FOV_001_RFP.tiff`

### TIFF Metadata

Use `tifffile.imwrite` with ImageJ-compatible metadata:

```python
pixel_size_um = fov_info.pixel_size_um
resolution = (1.0 / pixel_size_um, 1.0 / pixel_size_um) if pixel_size_um else None

tifffile.imwrite(
    str(path),
    data,
    imagej=True,
    resolution=resolution,
    metadata={"unit": "um"} if pixel_size_um else None,
)
```

### Output Directory

```
{experiment}/exports/tiff/
```

Created automatically if it doesn't exist. Same parent as CSV exports (`exports/`).

### Error Handling

- **Missing channel data:** Skip channel, log warning, continue with other channels
- **Disk full / permission error:** Catch `OSError`, report which files succeeded before failure
- **No FOVs in experiment:** Show message "No FOVs found in experiment" and return (match existing pattern)

### Edge Cases

- **Filename collision:** If sanitization causes two FOVs to produce the same filename, append `_2`, `_3`, etc.
- **Large images:** `read_image_numpy()` materializes the full array. For typical microscopy (up to 4096x4096 uint16 = ~32MB per channel), this is fine. No streaming needed for v1.
- **Dtype preservation:** Write whatever dtype the zarr stores (`uint8`, `uint16`, `float32`, etc.). Do not convert.

## Implementation Phases

### Phase 1: Core export function + tests
- [ ] Create `src/percell3/core/tiff_export.py` with `export_fov_as_tiff()`
- [ ] Handle filename sanitization and collision detection
- [ ] Include ImageJ pixel size metadata
- [ ] Handle missing channels gracefully (skip + warn)
- [ ] Create `tests/test_core/test_tiff_export.py`
  - [ ] Test basic single-FOV export (all channels written)
  - [ ] Test filename sanitization (spaces, parens)
  - [ ] Test missing channel data (skip + warn)
  - [ ] Test overwrite=False raises FileExistsError
  - [ ] Test overwrite=True replaces files
  - [ ] Test pixel size metadata round-trip
  - [ ] Test dtype preservation (uint8, uint16, float32)
  - [ ] Test empty FOV (no channels) produces no files

### Phase 2: CLI Data menu integration
- [ ] Add `MenuItem("4", "Export FOVs as TIFF", ...)` to `_data_menu()` in `menu.py`
- [ ] Implement `_export_tiff(state)` handler
  - [ ] FOV table display + selection (reuse `_show_fov_status_table` / `_select_fovs_from_table`)
  - [ ] Overwrite prompt if files exist
  - [ ] Progress bar via `make_progress()`
  - [ ] Summary message on completion
- [ ] Handle no-FOV case gracefully

### Phase 3: Napari viewer button
- [ ] Create `src/percell3/segment/viewer/tiff_export_widget.py`
  - [ ] `TiffExportWidget` class with QPushButton
  - [ ] On click: call `export_fov_as_tiff(store, fov_id, output_dir, overwrite=True)`
  - [ ] Status feedback in napari viewer (status bar or label)
- [ ] Register widget in `_viewer.py:_launch()` as dock widget
- [ ] Test widget creation (unit test, no napari required)

## Acceptance Criteria

### Functional
- [ ] `export_fov_as_tiff()` exports all channels for a FOV as individual TIFFs
- [ ] Exported TIFFs have correct pixel size metadata (ImageJ-compatible)
- [ ] Exported TIFFs preserve original dtype
- [ ] CLI Data menu shows "Export FOVs as TIFF" option
- [ ] User can select multiple FOVs (including derived) for batch export
- [ ] Progress bar shown during batch export
- [ ] Overwrite prompt when files exist (CLI)
- [ ] Napari viewer has "Export FOV as TIFF" button
- [ ] Viewer export re-reads from store (not layer data)
- [ ] Missing channels skipped with warning (not fatal)

### Quality
- [ ] All existing tests pass
- [ ] New tests for core export function
- [ ] Handles edge cases (empty experiment, missing channels, filename collision)

## Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `src/percell3/core/tiff_export.py` | **Create** | Core export function |
| `tests/test_core/test_tiff_export.py` | **Create** | Tests for export function |
| `src/percell3/cli/menu.py` | **Modify** | Add menu item + handler to `_data_menu` |
| `src/percell3/segment/viewer/tiff_export_widget.py` | **Create** | Napari export button widget |
| `src/percell3/segment/viewer/_viewer.py` | **Modify** | Register export widget |

## References

- **Brainstorm:** `docs/brainstorms/2026-02-27-tiff-export-feature-brainstorm.md`
- **tifffile API:** Already a core dependency (`pyproject.toml:36`)
- **Export patterns:** `src/percell3/core/experiment_store.py:959` (`export_csv`), `:972` (`export_prism_csv`)
- **Menu patterns:** `src/percell3/cli/menu.py:328` (`_data_menu`)
- **FOV model:** `src/percell3/core/models.py` (`FovInfo`)
- **Image read:** `src/percell3/core/experiment_store.py:369` (`read_image_numpy`)
- **Viewer widgets:** `src/percell3/segment/viewer/cellpose_widget.py` (widget pattern)
- **Filename sanitization:** Split-halo plugin `src/percell3/plugins/builtin/split_halo_condensate_analysis.py:481` (safe condition naming)
- **Learnings:** `docs/solutions/ui-bugs/cli-tkinter-file-dialog-state-reset.md` (file dialog bugs)
- **Related todo:** `todos/102-pending-p2-native-file-picker-missing-from-path-inputs.md`
