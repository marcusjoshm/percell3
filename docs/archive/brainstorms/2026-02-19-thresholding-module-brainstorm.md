---
title: Thresholding Module for PerCell 3
type: feat
date: 2026-02-19
status: decided
---

# Thresholding Module for PerCell 3

## What We're Building

A three-engine thresholding module that handles the full PerCell workflow for analyzing polyclonal cell populations:

1. **CellGrouper** — Groups cells by expression level using GMM (Gaussian Mixture Model) with BIC-based auto-selection of component count
2. **ThresholdEngine** (enhanced) — Per-group Otsu thresholding with napari live preview, optional ROI drawing, and accept/skip per group
3. **ParticleAnalyzer** — Full morphometric analysis of particles (connected components) within threshold masks, stored in a new `particles` table

### The Problem

Polyclonal cell populations express fluorescent proteins at different levels. Standard Otsu thresholding fails because pixel intensities vary across cells — the same cellular feature thresholds differently in high-expressing vs low-expressing cells. Grouping cells by expression level creates subpopulations where Otsu works correctly.

### End-to-End Workflow (Per FOV)

1. User selects a **grouping channel** + **metric** (mean, total, median fluorescence, size, etc.)
2. GMM fits to the metric values across all cells in the FOV; BIC auto-selects component count
3. Each cell is assigned to a group (stored as tags)
4. User selects a **thresholding channel** (may be same or different from grouping channel)
5. For each group (one at a time):
   a. Create **group image**: full FOV with only group cells visible (everything else zeroed using label masks)
   b. Open in **napari** with live Otsu threshold preview overlay
   c. User optionally draws **ROI** to restrict Otsu computation region
   d. User **accepts** (binary mask saved) or **skips** (no features visible, no mask)
   e. Option to **skip remaining groups** for efficiency
6. **Particle analysis** on accepted masks: find connected components within each cell boundary, measure full morphometrics
7. Store individual particles in `particles` table + per-cell summary measurements

## Why This Approach

### Three Composable Engines (vs. Monolith or Plugins)

- **CellGrouper** can be reused for any downstream analysis needing expression-level groups
- **ThresholdEngine** already exists for basic thresholding; we extend it with napari QC
- **ParticleAnalyzer** is independently useful for any binary mask analysis
- Each engine is testable without the others
- Follows the SegmentationEngine pattern established in the codebase
- Plugin system isn't built yet — building it first would delay the core workflow

### GMM Over Quantiles/K-Means

- GMM naturally models polyclonal expression as mixture of Gaussians
- BIC auto-selects the number of subpopulations — no manual guesswork
- Produces soft assignments (probabilities) that could be useful later
- Better than quantiles (which assume uniform distribution) or k-means (which assumes spherical clusters)

### Per-FOV Grouping

- Each field of view may have different expression distributions
- Imaging conditions (illumination, focus) vary across FOVs
- Per-FOV keeps groups meaningful within their context

### Napari with Live Preview

- Matches the quality-checking requirement (critical part of the analysis)
- ROI drawing restricts Otsu to the feature of interest (same as ImageJ workflow)
- Live preview lets user see the mask before committing
- Accept/skip per group preserves the manual QC step
- One-at-a-time with batch skip is practical for large experiments

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Architecture | Three composable engines | Testable, reusable, follows existing patterns |
| Grouping method | GMM with BIC auto-select | Best fit for polyclonal populations |
| Group scope | Per-FOV | Expression varies across FOVs |
| Group image format | Full FOV, non-group cells zeroed | Same size as original, uses label masks |
| Threshold QC | Napari with live preview + ROI | Matches ImageJ workflow, adds preview |
| Review flow | One group at a time, batch skip | Focused, practical for large experiments |
| Channel flexibility | Grouping and thresholding channels independent | Supports both same-channel and cross-channel workflows |
| Particle storage | New `particles` table + per-cell summaries | Full data for exploration + fast queries for reports |
| Threshold skip | No mask stored for skipped groups | Clean semantics: no mask = no features |

## Resolved Questions

1. **Napari interaction model**: Synchronous/blocking, matching the existing `segment/viewer/_viewer.py` pattern. Open napari, call `napari.run()`, read results after close.

2. **Re-thresholding behavior**: Replace old particles (like re-segmentation replaces cells). Delete old particles for the FOV before creating new ones. Clean slate each time.

3. **Typical group count**: Varies widely (2-10+) depending on the population. The "skip remaining" option is important for large group counts.

4. **Particle mask storage**: Yes, store an int32 particle label image in zarr (like segmentation labels). Each particle gets a unique integer ID. Enables visualization and re-analysis.

## Technology

- `sklearn.mixture.GaussianMixture` for GMM + BIC
- `skimage.filters.threshold_otsu` (already used)
- `scipy.ndimage.label` + `scipy.ndimage.find_objects` for particle detection
- `skimage.measure.regionprops` for particle morphometrics
- `napari` for interactive QC (already a dependency)
- New `particles` SQLite table for individual particle data
- Existing `measurements` table for per-cell summaries
- Existing `masks.zarr` for binary mask storage
- Existing `cell_tags` for group assignment

## Existing Code to Build On

- `src/percell3/measure/thresholding.py` — ThresholdEngine with `threshold_fov()`, all 5 methods
- `src/percell3/measure/measurer.py` — Bbox-optimized per-cell measurement pattern
- `src/percell3/measure/metrics.py` — MetricRegistry with built-in metrics
- `src/percell3/segment/_engine.py` — Batch FOV processing pattern
- `src/percell3/core/experiment_store.py` — mask I/O, threshold runs, cell tags
- `src/percell3/core/schema.py` — threshold_runs table, will need particles table
- `src/percell3/cli/menu.py` — Menu item 6 placeholder, Rich tables, numbered selection
