# Split-Halo Condensate Analysis Plugin — Brainstorm

**Date:** 2026-02-26
**Status:** Draft

## What We're Building

A new `AnalysisPlugin` called `split_halo_condensate_analysis` for analyzing bimolecular fluorescence complementation (BiFC) assays using reversible split-Halo sensors. The plugin measures fluorescence in two compartments of each cell:

1. **Condensed phase (RNP granules):** Per-particle measurements using the same ring-based local background subtraction approach as `local_bg_subtraction`. Reuses `bg_subtraction_core.py` algorithms.

2. **Dilute phase (surrounding cytoplasm):** Per-cell measurements of everything inside the cell segmentation boundary but outside a dilated particle mask. Uses the same Gaussian-peak histogram method to estimate and subtract background.

Additionally, the plugin creates **derived FOV images** for visualization with the `surface_plot_3D` plugin:
- **Condensed phase FOVs:** Full FOV images where only granule pixels retain intensity (everything else zeroed). All channels copied.
- **Dilute phase FOVs:** Full FOV images where only dilute phase pixels retain intensity (everything inside the dilated particle mask zeroed). All channels copied.

## Why This Approach

- **Separate plugin** (not extending `local_bg_subtraction`): The condensate analysis has a distinct use case (BiFC split-Halo assays), different output structure (two measurement types + derived images), and different granularity (per-particle + per-cell). Keeping it separate avoids overcomplicating the existing plugin.

- **Reuse `bg_subtraction_core.py`**: The core algorithms (ring computation, Gaussian-peak background estimation) are already factored out into a pure-numpy module. The new plugin can call the same functions.

- **New FOVs for derived images**: The user wants derived images to appear alongside originals in the experiment, accessible by any existing tool (including `surface_plot_3D`) without modifications. New FOVs named `condensed_phase_{original_name}` and `dilute_phase_{original_name}` achieve this naturally.

- **Separate dilation parameters**: The ring dilation for granule background estimation and the exclusion zone dilation for the dilute phase serve different purposes and may need different values.

## Key Decisions

1. **Plugin name:** `split_halo_condensate_analysis` (Python module: `split_halo_condensate_analysis.py`)

2. **Granule measurements:** Per-particle, same as `local_bg_subtraction` — ring dilation, Gaussian-peak BG estimation, BG-subtracted mean/integrated intensity

3. **Dilute phase measurements:** Per-cell. Region = (cell segmentation mask) AND NOT (dilated particle mask). Background estimated via Gaussian-peak method on the histogram of dilute phase pixels.

4. **Derived images are raw:** No background subtraction applied to saved images. BG subtraction is quantification-only (reported in CSV).

5. **Derived images stored as new FOVs:** Prefixed names (`condensed_phase_*`, `dilute_phase_*`), all channels from original FOV masked and copied.

6. **Full FOV scope:** Derived images are full-FOV (not cropped per-cell or per-particle), with non-relevant pixels zeroed.

7. **Separate CSVs:** One for per-particle granule data, one for per-cell dilute phase data. Exported per condition.

8. **Two dilation parameters:** `ring_dilation_pixels` (for granule BG ring) and `exclusion_dilation_pixels` (for dilute phase exclusion zone).

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `measurement_channel` | str | required | Channel to measure intensities from |
| `particle_channel` | str | required | Channel whose particle mask defines granules |
| `exclusion_channel` | str \| None | None | Optional channel mask to exclude from BG ring |
| `ring_dilation_pixels` | int | 5 | Dilation for granule background ring |
| `exclusion_dilation_pixels` | int | 5 | Dilation for dilute phase exclusion zone |
| `max_background` | float \| None | None | Upper bound on background estimate |
| `export_csv` | bool | True | Export per-particle and per-cell CSVs |
| `save_images` | bool | True | Create derived condensed/dilute phase FOVs |

## CSV Output

### Granule CSV (per-particle, per-condition)
Same columns as `local_bg_subtraction`:
`particle_id, cell_id, fov_id, fov_name, condition, bio_rep, area_pixels, raw_mean_intensity, raw_integrated_intensity, bg_estimate, bg_ring_pixels, bg_sub_mean_intensity, bg_sub_integrated_intensity`

Plus `norm_mean_intensity` if `normalization_channel` is specified.

### Dilute Phase CSV (per-cell, per-condition)
`cell_id, fov_id, fov_name, condition, bio_rep, dilute_area_pixels, raw_mean_intensity, raw_integrated_intensity, bg_estimate, bg_sub_mean_intensity, bg_sub_integrated_intensity`

## Algorithm Overview

### Per cell:
1. Read cell segmentation mask, particle labels, and measurement channel image
2. Crop to cell bounding box

**Granule (per-particle within cell):**
3. For each particle: compute BG ring (dilate by `ring_dilation_pixels`, exclude other particles and optional exclusion mask)
4. Estimate BG via Gaussian-peak histogram method on ring pixels
5. Compute raw and BG-subtracted mean/integrated intensity

**Dilute phase (per-cell):**
6. Create diluted particle mask: dilate all particles by `exclusion_dilation_pixels`
7. Dilute region = cell_mask AND NOT dilated_particle_mask
8. Estimate BG via Gaussian-peak histogram method on dilute region pixels
9. Compute raw and BG-subtracted mean/integrated intensity

### Derived image creation (per FOV):
10. For each channel in the FOV:
    - Condensed phase image: original × (particle_mask > 0), i.e., zero everything outside particles
    - Dilute phase image: original × dilute_region_mask, i.e., zero everything inside dilated particles
11. Register new FOVs (`condensed_phase_{name}`, `dilute_phase_{name}`) with same condition/metadata
12. Write all channels to the new FOVs

## Resolved Questions

- **Dilute phase granularity:** Per-cell (not per-particle)
- **Image background subtraction:** Images are raw, BG subtraction is quantification-only
- **Storage approach:** New FOVs in the same experiment, not new channels or separate zarr groups
- **Channel scope:** All channels from original FOV are masked and written to derived FOVs

## Additional Feature: Expanded Surface Plot Colormaps

The surface plot widget currently offers a limited colormap list: `viridis, plasma, magma, inferno, turbo, hot, gray`.

For better visualization of condensate and dilute phase surface plots, expand the colormap dropdown with additional matplotlib colormaps:

**Colormaps to add:**
- `nipy_spectral` — full-spectrum rainbow, good for dense data
- `Spectral` — diverging red-yellow-green-blue
- `rainbow` — classic full-spectrum
- `coolwarm` — diverging blue-red, good for showing contrast
- `gnuplot` — dark-to-bright multi-hue
- `jet` — classic rainbow (red-blue)
- `cividis` — colorblind-friendly alternative to viridis

These are all standard matplotlib colormaps that napari already supports — the change is just adding their names to the `_COLORMAPS` list in `surface_plot_widget.py`.

## Open Questions

None — all design questions resolved during brainstorming.
