# Background Subtraction Plugin — Brainstorm

**Date:** 2026-03-04
**Status:** Ready for planning

## What We're Building

A `BackgroundSubtractionPlugin` that performs per-threshold-layer background subtraction on a selected channel and produces derived FOVs as full DB records with new zarr arrays. The plugin:

1. Prompts the user to select FOVs (only those with threshold layers) and a single channel.
2. For each FOV + threshold layer combo, estimates the background value using histogram peak detection (50-bin histogram, Gaussian smoothing, prominence-based peak selection).
3. Subtracts the background from masked pixels (clip at zero), leaving unmasked pixels as zero.
4. Registers a new FOV in the DB with the derived image, inheriting all source metadata.
5. Saves histogram PNGs to `exports/bgsub_histograms/` for visual verification.

## Why This Approach

Follows the established split_halo plugin pattern exactly — `AnalysisPlugin` subclass, custom CLI handler, `store.add_fov()` + `store.write_image()`. No new DB tables or abstractions needed.

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Derived FOV metadata | Copy all (condition, bio_rep, pixel_size_um, timepoint) | Makes derived FOVs queryable alongside originals |
| Provenance storage | Reuse existing `analysis_runs` system | Background values stored in `custom_outputs` JSON — no new table |
| Derived FOV capabilities | Full FOV with whole_field segmentation + fov_config | Derived FOVs can be measured, thresholded, analyzed further |
| Output dtype | Match source dtype, clip at zero | Keeps file sizes small, consistent with source data |
| Peak detection code | New shared module (`plugins/builtin/peak_detection.py`) | Both this plugin and split_halo can import from it without coupling |
| Plugin location | `src/percell3/plugins/builtin/background_subtraction.py` | Consistent with other built-in plugins |
| CLI integration | Custom handler in `menu.py` (like `_run_condensate_analysis`) | Needed for multi-step interactive prompts |
| Naming convention | `{source_fov_name}_bgsub_{threshold_layer_name}_{channel_name}` | Clear provenance in the name itself |
| FOV filtering | Show all FOVs with thresholds (including derived) | User decides; chaining operations on derived FOVs is valid |
| Threshold selection | Process all configured thresholds automatically | Simpler UX; each threshold gets its own derived FOV |
| Interactivity | Batch process all, summary table at end | Faster workflow for many FOVs |
| Histogram export | One PNG per FOV/threshold combo in `exports/bgsub_histograms/` | Shows smoothed histogram with detected peak marked; visual verification |

## Scope

### In Scope
- Plugin class implementing `AnalysisPlugin` interface
- Interactive CLI handler (FOV multi-select, channel select, confirmation)
- `find_gaussian_peaks` extracted to shared `peak_detection.py` module
- Derived FOV creation with full metadata inheritance
- Histogram PNG export (one per FOV/threshold combo, smoothed histogram with peak marked)
- Rich summary table after processing
- Edge case handling (no threshold layers, no non-zero pixels, name collisions)

### Out of Scope
- Batch/non-interactive mode
- Undo/delete derived FOVs (can be done manually via existing FOV delete)
- Custom histogram parameters (hardcoded 50 bins, sigma=2, 15% prominence)
- Multi-channel background subtraction in one run (user re-runs for each channel)
- Threshold selection UI (all thresholds processed automatically)
