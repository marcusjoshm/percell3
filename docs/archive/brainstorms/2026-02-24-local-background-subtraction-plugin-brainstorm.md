# Brainstorm: Local Background Subtraction Plugin & Plugin Manager

**Date:** 2026-02-24
**Status:** Complete
**Next:** `/workflows:plan`

## What We're Building

Two things in sequence:

1. **Plugin Manager** — The PerCell 3 plugin system (registry, discovery, menu integration, base class). This enables all future analysis plugins.
2. **Local Background Subtraction Plugin** — The first real plugin, ported from PerCell 1's "m7G Cap Enrichment Analysis" but made universal and channel-agnostic.

### Plugin Manager

- `AnalysisPlugin` abstract base class with `execute(store, config)` interface
- `PluginRegistry` with hybrid discovery: built-in plugins from `plugins/builtin/` directory, entry-point discovery deferred for future third-party plugins
- `PluginInfo` dataclass for metadata (name, version, description, author)
- `PluginResult` dataclass for structured return values
- Menu item "Plugin manager" (currently disabled) wired up to list/run plugins

### Local Background Subtraction Plugin

A universal per-particle local background subtraction that replaces the original's hardcoded PB/SG/Cap channel logic with flexible user-selected channels.

**User selects:**
1. **Measurement channel** — The channel whose intensity will be background-subtracted
2. **Particle mask** — Which thresholded particle mask to use (dilated to create background ring)
3. **Exclusion mask** (optional) — Another particle mask whose pixels are removed from both the particle AND background ring before measurement

**Algorithm (per particle):**
1. Load the particle's binary mask from the existing particle data in ExperimentStore
2. If exclusion mask selected: subtract exclusion pixels from the particle mask
3. Dilate the particle mask by N pixels (configurable, default 5px) to create a background ring
4. If exclusion mask selected: subtract exclusion pixels from the background ring
5. Extract intensity values from the measurement channel within the background ring
6. Estimate background via Gaussian smoothing + peak detection on the ring's histogram (ported from original)
7. Compute background-subtracted intensity for the particle
8. Store results in ExperimentStore as new measurements AND export per-particle CSV

## Why This Approach

### Reuse existing particles
The plugin reads particles that already exist in ExperimentStore from prior thresholding runs. If no particle mask exists, it errors with instructions to run thresholding first. This avoids duplicating detection logic and keeps the plugin focused on its core task: background estimation and subtraction.

### Python over ImageJ macros
The original used three ImageJ macros (`pb_background_subtraction.ijm`, `sg_background_subtraction.ijm`, `pb_only_background_subtraction.ijm`) for dilation, mask subtraction, and ROI extraction. All of this is straightforward with scipy.ndimage and numpy — no external process needed, faster, and testable.

### Flexible channel selection over hardcoded configs
The original had 4 hardcoded analysis configurations (`PB_Cap`, `DDX6`, `SG_Cap`, `G3BP1`) with fixed channel assignments. The new plugin asks the user which channels to use, making it universal for any experiment.

### Gaussian peak detection for background estimation
The original's histogram-based approach (Gaussian smooth → find dominant peak) is robust to bright contaminating structures in the background ring. Simpler alternatives like median would be less reliable.

### Plugin manager first
Building the plugin infrastructure before the plugin itself establishes patterns for all future plugins and avoids tech debt from a standalone handler approach.

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Data source | Reuse existing particles from ExperimentStore | Avoids duplicate detection; error if missing |
| Exclusion mask behavior | Remove from both particle AND background ring | Matches original macro behavior |
| Dilation amount | Configurable per-run with default (5px) | Original used 2-5px depending on particle type |
| Background estimation | Gaussian peak detection (ported from original) | Proven robust; simpler alternatives less reliable |
| Output storage | Both ExperimentStore measurements AND CSV export | Full integration + easy external analysis |
| Histogram visualization | Optional, off by default | QC when needed, avoids file bloat |
| Plugin discovery | Hybrid: directory for built-ins, entry-points deferred | Matches existing spec, YAGNI for third-party |
| Build order | Plugin manager first, then this plugin | Sets foundation for all future plugins |

## Original m7G Cap Enrichment Analysis Summary

The original PerCell 1 plugin (`IntensityAnalysisBSAutoPlugin`) worked as follows:

1. **Preprocessing** (`BSWorkflow` + `BSPreprocessingService`):
   - Prepared directory structure for background subtraction
   - Detected channel naming patterns (ch0=Cap, ch1=SG, ch2=PB)
   - Ran ImageJ macros to create processed masks

2. **ImageJ Macros** (3 variants):
   - `pb_background_subtraction.ijm`: Opened ch2 mask, subtracted ch1 (SG) ROIs, extracted PB ROIs, dilated by 2px
   - `sg_background_subtraction.ijm`: Opened ch1 mask, extracted SG ROIs, dilated by 5px
   - `pb_only_background_subtraction.ijm`: Same as PB but no SG subtraction, dilated by 5px

3. **Intensity Analysis** (`IntensityAnalysisBSPlugin`):
   - For each ROI: created background ring via dilation, extracted ring pixel intensities
   - Smoothed histogram with Gaussian kernel (sigma=2), found dominant peak as background estimate
   - Computed per-ROI: raw intensity, background estimate, background-subtracted intensity
   - Saved per-ROI CSV and optional histogram plots

4. **Hardcoded Configurations**: 4 analysis configs mapping specific channels:
   - `PB_Cap`: particle=PB channel, measure=Cap channel, exclude=SG
   - `DDX6`: particle=PB channel, measure=DDX6 channel, exclude=SG
   - `SG_Cap`: particle=SG channel, measure=Cap channel, exclude=none
   - `G3BP1`: particle=SG channel, measure=G3BP1 channel, exclude=none

## Open Questions

None — all questions resolved during brainstorming.

## Resolved Questions

1. **Data source?** → Reuse existing particles from ExperimentStore. Error with instructions if no particle mask exists.
2. **Exclusion mask behavior?** → Remove exclusion pixels from both particle mask and background ring.
3. **Dilation amount?** → Configurable with default (5px). Original used 2-5px.
4. **Background estimation method?** → Keep Gaussian peak detection, port from original Python code.
5. **Output storage?** → Both ExperimentStore measurements and auto-exported CSV.
6. **Build order?** → Plugin manager first, then this plugin.
7. **Histogram visualization?** → Optional flag, off by default.
8. **Plugin discovery approach?** → Hybrid: directory-based for built-ins, entry-points deferred.
