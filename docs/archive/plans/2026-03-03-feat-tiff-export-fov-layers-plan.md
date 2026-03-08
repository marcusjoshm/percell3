---
title: "feat: TIFF export for FOV layers (channels, labels, masks)"
type: feat
date: 2026-03-03
supersedes: docs/plans/2026-02-27-feat-tiff-export-for-fov-images-plan.md
---

# feat: TIFF export for FOV layers (channels, labels, masks)

## Overview

Export all configured layers for selected FOVs as individual `.tiff` files from the CLI Data menu. For each FOV, the export writes:

1. **Channel images** — one file per channel (original dtype)
2. **Segmentation labels** — one file per configured cellular segmentation (int32 label image)
3. **Threshold masks** — one file per configured threshold whose source is this FOV (uint8 0/255)

"Configured" means whatever segmentations and thresholds appear in the FOV's config matrix (`fov_config` table).

## Motivation

Users need TIFF exports for external tools (FIJI/ImageJ), sharing with collaborators, archival, and the 3D surface plot plugin. The existing brainstorm/plan (Feb 27) covered channel-only export. This plan extends it to also export segmentation labels and threshold masks — giving users a complete snapshot of their current analysis state.

## Proposed Solution

### Core Export Function

```python
# src/percell3/core/tiff_export.py

def export_fov_as_tiff(
    store: ExperimentStore,
    fov_id: int,
    output_dir: Path,
    overwrite: bool = False,
) -> ExportResult:
    """Export all configured layers for a FOV as individual TIFF files.

    Writes:
    - {fov_name}_{channel}.tiff for each channel
    - {fov_name}_{seg_name}_labels.tiff for each cellular segmentation in config
    - {fov_name}_{thr_name}_mask.tiff for each threshold in config (source_fov only)

    Returns ExportResult with written paths and skipped items.
    Raises FileExistsError if files exist and overwrite=False.
    """
```

```python
@dataclass
class ExportResult:
    written: list[Path]
    skipped: list[str]  # human-readable skip reasons
```

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Config source | `store.get_fov_config(fov_id)` | Authoritative source for what seg/thresholds are assigned |
| Seg deduplication | Unique `segmentation_id` across config entries | Avoid writing same label image twice |
| Threshold deduplication | Unique non-null `threshold_id` | Skip NULL threshold entries |
| Threshold ownership | Only export where `threshold.source_fov_id == fov_id` | Mask must spatially match the FOV |
| Whole-field segs | Exclude (`seg_type == "cellular"` only) | All-1 label images are not useful |
| No-config FOVs | Export channels only | Channel data exists even without analysis |
| Missing zarr data | Skip + collect warning, continue | Never abort the whole export |
| File extension | `.tiff` | Consistent with existing plan |
| Output directory | `{experiment}/exports/tiff/` | Consistent with CSV exports in `exports/` |

### File Naming

```
{sanitized_fov_name}_{channel_name}.tiff          # channels
{sanitized_fov_name}_{seg_name}_labels.tiff        # segmentation labels
{sanitized_fov_name}_{thr_name}_mask.tiff          # threshold masks
```

Sanitization: `name.replace(" ", "_").replace("(", "").replace(")", "")` — matches existing plan convention.

Collision detection: track all written filenames within the export run; append `_2`, `_3` etc. if duplicate.

### TIFF Metadata

```python
pixel_size_um = fov_info.pixel_size_um
resolution = (1.0 / pixel_size_um, 1.0 / pixel_size_um) if pixel_size_um else None

tifffile.imwrite(
    str(path), data, imagej=True,
    resolution=resolution,
    metadata={"unit": "um"} if pixel_size_um else None,
)
```

### Error Handling

- **Missing zarr data**: Catch `(KeyError, Exception)` around each `read_*` call. Add to `skipped` list, continue.
- **Disk full / permission**: Catch `OSError` on `tifffile.imwrite`, report partial results.
- **No FOVs**: Show "No FOVs found" and return.
- **No config entries for FOV**: Export channels only, note "no analysis layers configured" in summary.

## Implementation

### Phase 1: Core export function + tests

- [ ] Create `src/percell3/core/tiff_export.py`
  - [ ] `ExportResult` dataclass
  - [ ] `_sanitize_filename(name: str) -> str` helper
  - [ ] `export_fov_as_tiff(store, fov_id, output_dir, overwrite)` function
    - [ ] Read FOV info for pixel_size_um and display_name
    - [ ] Export all channels via `store.get_channels()` + `store.read_image_numpy()`
    - [ ] Read config via `store.get_fov_config(fov_id)`
    - [ ] Deduplicate: collect unique seg_ids (cellular only) and unique non-null threshold_ids
    - [ ] For each unique seg_id: `store.read_labels(seg_id)` → write `_labels.tiff`
    - [ ] For each unique thr_id where `thr.source_fov_id == fov_id`: `store.read_mask(thr_id)` → write `_mask.tiff`
    - [ ] Track collisions, skip on missing data
- [ ] Create `tests/test_core/test_tiff_export.py`
  - [ ] Test basic export: channels + seg labels + threshold mask all written
  - [ ] Test filename sanitization
  - [ ] Test overwrite=False raises FileExistsError
  - [ ] Test overwrite=True replaces files
  - [ ] Test missing channel data skipped with warning
  - [ ] Test missing label data skipped with warning
  - [ ] Test FOV with no config exports channels only
  - [ ] Test whole-field segmentation excluded
  - [ ] Test threshold not exported when source_fov_id != fov_id
  - [ ] Test pixel size metadata round-trip via tifffile.imread
  - [ ] Test dtype preservation (uint16 channel stays uint16)
  - [ ] Test multiple seg/threshold deduplication (same seg_id in 2 config entries → 1 file)

### Phase 2: CLI Data menu integration

- [ ] Add `MenuItem("4", "Export FOVs as TIFF", ...)` to `_data_menu()` in `src/percell3/cli/menu.py`
- [ ] Implement `_export_tiff(state)` handler
  - [ ] `store = state.require_experiment()`
  - [ ] FOV table display + selection (reuse `_show_fov_status_table` / `_select_fovs_from_table`)
  - [ ] Create output dir: `store.path / "exports" / "tiff"` with `mkdir(parents=True, exist_ok=True)`
  - [ ] Overwrite check: if any expected output files exist, prompt y/n
  - [ ] Progress bar via `make_progress()` — per FOV granularity
  - [ ] Collect all results, print summary: "Exported N files to exports/tiff/"
  - [ ] Print skipped items if any
- [ ] Lazy import `tiff_export` inside handler (CLI startup speed)

## Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `src/percell3/core/tiff_export.py` | **Create** | Core export function + ExportResult |
| `tests/test_core/test_tiff_export.py` | **Create** | Unit tests |
| `src/percell3/cli/menu.py` | **Modify** | Add menu item + handler to `_data_menu` |

## Acceptance Criteria

- [ ] `export_fov_as_tiff()` exports channels, cellular seg labels, and threshold masks as individual TIFFs
- [ ] Exported TIFFs have correct pixel size metadata (ImageJ-compatible)
- [ ] Exported TIFFs preserve original dtype
- [ ] Segmentation label TIFFs contain integer cell IDs (not binary)
- [ ] Threshold mask TIFFs are uint8 0/255
- [ ] Only cellular segmentations exported (whole_field excluded)
- [ ] Only thresholds where source_fov_id matches are exported
- [ ] Config entries with same seg_id produce only one label file
- [ ] Missing zarr data is skipped with warning (not fatal)
- [ ] FOVs without config entries still export channel images
- [ ] CLI Data menu shows "Export FOVs as TIFF" option
- [ ] User can select multiple FOVs for batch export
- [ ] Progress bar shown during export
- [ ] Overwrite prompt when files exist
- [ ] All existing tests pass

## Verification

```bash
pytest tests/test_core/test_tiff_export.py -v
pytest tests/ -x
```

## References

- **Superseded plan:** `docs/plans/2026-02-27-feat-tiff-export-for-fov-images-plan.md` (channel-only)
- **Brainstorm:** `docs/brainstorms/2026-02-27-tiff-export-feature-brainstorm.md`
- **tifffile:** Already a dependency (`pyproject.toml`)
- **Export patterns:** `src/percell3/core/experiment_store.py:1575` (`export_particles_csv`)
- **Menu patterns:** `src/percell3/cli/menu.py:329` (`_data_menu`)
- **Config matrix:** `src/percell3/core/experiment_store.py` (`get_fov_config`)
- **Read methods:** `read_image_numpy` (:405), `read_labels` (:559), `read_mask` (:747)
- **Models:** `FovConfigEntry` (:110), `SegmentationInfo` (:56), `ThresholdInfo` (:73) in `models.py`
- **Learnings:** CLI lazy imports, zarr KeyError handling, Rich markup escaping
