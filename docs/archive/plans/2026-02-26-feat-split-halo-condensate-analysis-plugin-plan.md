---
title: "feat: Add split-Halo condensate analysis plugin"
type: feat
date: 2026-02-26
brainstorm: docs/brainstorms/2026-02-26-split-halo-condensate-analysis-brainstorm.md
---

# feat: Add split-Halo condensate analysis plugin

## Overview

New `AnalysisPlugin` for BiFC split-Halo sensor experiments that measures both condensed phase (RNP granules) and dilute phase (surrounding cytoplasm) separately. Creates derived FOV images for 3D surface plot visualization. Also expands the surface plot widget's colormap options.

## Problem Statement / Motivation

Bimolecular fluorescence complementation assays using reversible split-Halo sensors require separate quantification of signal in RNP granules vs. the surrounding dilute phase. The existing `local_bg_subtraction` plugin only measures particles — it does not measure the dilute phase or create derived images for visualization. A dedicated plugin is needed to:

1. Measure both compartments (condensed + dilute) in a single run
2. Generate masked FOV images that can be loaded into the `surface_plot_3D` plugin
3. Export separate CSVs at appropriate granularity (per-particle for granules, per-cell for dilute)

## Proposed Solution

### New Files

| File | Purpose |
|------|---------|
| `src/percell3/plugins/builtin/split_halo_condensate_analysis.py` | Plugin class |
| `tests/test_plugins/test_split_halo_condensate_analysis.py` | Tests |

### Modified Files

| File | Change |
|------|--------|
| `src/percell3/segment/viewer/surface_plot_widget.py` | Expand `_COLORMAPS` list |

## Technical Approach

### Phase 1: Plugin skeleton and granule measurement

Create `split_halo_condensate_analysis.py` with the `SplitHaloCondensateAnalysisPlugin` class inheriting from `AnalysisPlugin`.

**`info()`** — returns `PluginInfo(name="split_halo_condensate_analysis", ...)`.

**`validate()`** — same checks as `local_bg_subtraction`: channels exist, cells exist, threshold runs exist.

**`get_parameter_schema()`** — JSON Schema with these properties:

```python
{
    "type": "object",
    "properties": {
        "measurement_channel": {"type": "string", "description": "Channel for intensity measurement"},
        "particle_channel": {"type": "string", "description": "Channel whose particle mask defines granules"},
        "exclusion_channel": {"type": ["string", "null"], "default": None},
        "ring_dilation_pixels": {"type": "integer", "default": 5, "description": "Dilation for granule BG ring"},
        "exclusion_dilation_pixels": {"type": "integer", "default": 5, "description": "Dilation for dilute phase exclusion zone"},
        "max_background": {"type": ["number", "null"], "default": None},
        "export_csv": {"type": "boolean", "default": True},
        "save_images": {"type": "boolean", "default": True},
    },
    "required": ["measurement_channel", "particle_channel"],
}
```

**`run()` — granule measurement portion:**
Follows the same pattern as `local_bg_subtraction.py:124-323`:
1. Extract params, find threshold runs for `particle_channel`
2. Determine FOV list from `cell_ids` or `store.get_fovs()`
3. Loop FOVs → read `cell_labels`, `particle_labels`, `measurement_image`, optional `exclusion_mask`
4. Loop cells → crop to bounding box, call `process_particles_for_cell()` from `bg_subtraction_core`
5. Collect per-particle rows in `granule_rows_by_condition: defaultdict(list)`

**Key reuse:** Import `process_particles_for_cell` from `percell3.plugins.builtin.bg_subtraction_core` — same function, same parameters, same output.

### Phase 2: Dilute phase measurement

Within the same per-cell loop (after granule measurement), compute the dilute phase:

```python
from scipy.ndimage import binary_dilation
from skimage.morphology import disk

# All particles in cell (already computed by process_particles_for_cell context)
all_particles_mask = (particle_crop > 0) & cell_mask

# Dilate all particles to create exclusion zone
dilated_particles = binary_dilation(
    all_particles_mask,
    structure=disk(exclusion_dilation_pixels),
)

# Dilute region = inside cell, outside dilated particles
dilute_mask = cell_mask & ~dilated_particles
dilute_pixels = int(np.sum(dilute_mask))

if dilute_pixels > 0:
    dilute_intensities = meas_crop[dilute_mask].astype(np.float64)
    raw_mean = float(np.mean(dilute_intensities))
    raw_integrated = float(np.sum(dilute_intensities))

    # Same Gaussian-peak BG estimation on dilute region histogram
    bg_result = estimate_background_gaussian(
        dilute_intensities, max_background=max_background,
    )
    bg_value = bg_result[0] if bg_result else 0.0

    bg_sub_mean = raw_mean - bg_value
    bg_sub_integrated = raw_integrated - (bg_value * dilute_pixels)
```

Collect per-cell rows in `dilute_rows_by_condition: defaultdict(list)`.

**Dilute CSV columns:**
`cell_id, fov_id, fov_name, condition, bio_rep, dilute_area_pixels, raw_mean_intensity, raw_integrated_intensity, bg_estimate, bg_sub_mean_intensity, bg_sub_integrated_intensity`

### Phase 3: Derived FOV image creation

After processing all cells in a FOV, create the two derived FOV images. This runs once per FOV (not per cell).

**Build full-FOV masks from cell-level crops:**

```python
# Initialize full-FOV masks
condensed_mask = np.zeros((height, width), dtype=bool)  # particles only
dilute_mask_full = np.zeros((height, width), dtype=bool)  # dilute only

for _, cell_row in cells_df.iterrows():
    bx, by, bw, bh = int(cell_row["bbox_x"]), int(cell_row["bbox_y"]), ...
    label_val = int(cell_row["label_value"])

    cell_mask = cell_labels[by:by+bh, bx:bx+bw] == label_val
    particle_crop = particle_labels[by:by+bh, bx:bx+bw]

    all_particles = (particle_crop > 0) & cell_mask
    condensed_mask[by:by+bh, bx:bx+bw] |= all_particles

    dilated = binary_dilation(all_particles, structure=disk(exclusion_dilation_pixels))
    dilute_region = cell_mask & ~dilated
    dilute_mask_full[by:by+bh, bx:bx+bw] |= dilute_region
```

**Register and write derived FOVs:**

```python
if save_images:
    channels = store.get_channels()

    # Create condensed phase FOV
    condensed_fov_id = store.add_fov(
        condition=fov_info.condition,
        bio_rep=fov_info.bio_rep,
        display_name=f"condensed_phase_{fov_info.display_name}",
        width=fov_info.width,
        height=fov_info.height,
        pixel_size_um=fov_info.pixel_size_um,
    )
    for ch in channels:
        ch_image = store.read_image_numpy(fov_id, ch.name)
        masked = np.where(condensed_mask, ch_image, 0)
        store.write_image(condensed_fov_id, ch.name, masked)

    # Create dilute phase FOV
    dilute_fov_id = store.add_fov(
        condition=fov_info.condition,
        bio_rep=fov_info.bio_rep,
        display_name=f"dilute_phase_{fov_info.display_name}",
        width=fov_info.width,
        height=fov_info.height,
        pixel_size_um=fov_info.pixel_size_um,
    )
    for ch in channels:
        ch_image = store.read_image_numpy(fov_id, ch.name)
        masked = np.where(dilute_mask_full, ch_image, 0)
        store.write_image(dilute_fov_id, ch.name, masked)
```

**Important:** Images are raw intensities (not background-subtracted). BG subtraction is quantification-only.

### Phase 4: CSV export

Two separate export methods following the pattern from `local_bg_subtraction.py:325-358`:

**Granule CSVs:** `condensate_granule_{meas_channel}_{condition}_{timestamp}.csv`
- Same columns as `local_bg_subtraction`: `particle_id, cell_id, fov_id, fov_name, condition, bio_rep, area_pixels, raw_mean_intensity, raw_integrated_intensity, bg_estimate, bg_ring_pixels, bg_sub_mean_intensity, bg_sub_integrated_intensity`

**Dilute CSVs:** `condensate_dilute_{meas_channel}_{condition}_{timestamp}.csv`
- Columns: `cell_id, fov_id, fov_name, condition, bio_rep, dilute_area_pixels, raw_mean_intensity, raw_integrated_intensity, bg_estimate, bg_sub_mean_intensity, bg_sub_integrated_intensity`

Both write to `Path(store.path) / "exports"` using `csv.DictWriter`.

### Phase 5: Colormap expansion

In `surface_plot_widget.py` line 20, expand the `_COLORMAPS` list:

```python
# Before:
_COLORMAPS = ["viridis", "plasma", "magma", "inferno", "turbo", "hot", "gray"]

# After:
_COLORMAPS = [
    "viridis", "plasma", "magma", "inferno", "turbo", "hot", "gray",
    "nipy_spectral", "Spectral", "rainbow", "coolwarm", "gnuplot", "jet", "cividis",
]
```

These are all standard matplotlib colormaps supported by napari.

### Phase 6: Tests

Create `tests/test_plugins/test_split_halo_condensate_analysis.py` following the pattern from `tests/test_plugins/test_local_bg_subtraction.py`.

**Test helper:** `_create_condensate_experiment(tmp_path)` that builds a synthetic experiment with:
- Two channels (e.g., DAPI + GFP)
- Segmentation labels with known cell regions
- Particle labels with known granule positions and intensities
- Known background level for verifiable BG subtraction

**Test classes:**

1. **`TestPluginInfo`** — verify `info()` returns correct `PluginInfo`
2. **`TestValidation`** — test `validate()` catches missing channels, cells, thresholds
3. **`TestGranuleMeasurement`** — verify per-particle BG subtraction matches expected values (same algorithm as local_bg_subtraction)
4. **`TestDilutePhase`** — verify dilute region computation:
   - Dilute mask = cell_mask AND NOT dilated_particle_mask
   - BG estimation on dilute pixels
   - Correct raw/BG-subtracted values
5. **`TestDerivedFOVCreation`** — verify:
   - New FOVs registered with correct metadata (condition, bio_rep, dimensions, pixel_size)
   - Condensed phase FOV has nonzero pixels only where particles exist
   - Dilute phase FOV has nonzero pixels only in dilute region
   - All channels present in derived FOVs
   - Display names are `condensed_phase_{original}` and `dilute_phase_{original}`
6. **`TestCSVExport`** — verify:
   - Granule CSV has correct columns and row count
   - Dilute CSV has correct columns and one row per cell
   - Files written to `exports/` directory
7. **`TestEdgeCases`** — cells with no particles, cells where dilute region is empty after dilation

**Colormap test:** Add a simple test to verify the `_COLORMAPS` list contains the new entries (can go in `tests/test_plugins/test_surface_plot_3d.py` or a new test).

## Acceptance Criteria

- [x] Plugin auto-discovered by `PluginRegistry` (no manual registration)
- [x] Per-particle granule measurements match `local_bg_subtraction` algorithm exactly
- [x] Per-cell dilute phase measurement uses Gaussian-peak BG on dilute region histogram
- [x] Derived FOV images created with `condensed_phase_` and `dilute_phase_` prefixes
- [x] Derived FOVs contain all channels, masked to appropriate region, raw intensities
- [x] Derived FOVs visible in surface_plot_3D plugin without modifications
- [x] Separate CSVs exported per condition for granules and dilute phase
- [x] Surface plot widget shows expanded colormap dropdown with nipy_spectral, Spectral, rainbow, coolwarm, gnuplot, jet, cividis
- [x] All tests pass
- [x] No private ExperimentStore API usage (`_conn`, internal `queries`)
- [x] Explicit `dtype=np.float64` in all numpy reduction operations

## Dependencies & Risks

**Dependencies:**
- `bg_subtraction_core.py` — reused as-is, no modifications needed
- `ExperimentStore.add_fov()` + `write_image()` — existing API, used at import time
- `scipy.ndimage.binary_dilation` + `skimage.morphology.disk` — already in dependency tree

**Risks:**
- **Derived FOV display_name validation:** Names like `condensed_phase_control_N1_FOV_001` must pass `_validate_name()` regex `^[A-Za-z0-9][A-Za-z0-9 _.+()-]{0,254}$`. The underscore and alphanumeric characters are safe.
- **Re-running the plugin:** If run twice, it would create duplicate derived FOVs. Should check if derived FOVs already exist and skip or overwrite. Simplest approach: check for existing FOV with the derived display_name before creating.

## References

- Brainstorm: `docs/brainstorms/2026-02-26-split-halo-condensate-analysis-brainstorm.md`
- Local BG subtraction plugin: `src/percell3/plugins/builtin/local_bg_subtraction.py`
- BG subtraction core: `src/percell3/plugins/builtin/bg_subtraction_core.py`
- Surface plot widget: `src/percell3/segment/viewer/surface_plot_widget.py:20`
- Plugin base classes: `src/percell3/plugins/base.py`
- ExperimentStore FOV API: `src/percell3/core/experiment_store.py:240`
