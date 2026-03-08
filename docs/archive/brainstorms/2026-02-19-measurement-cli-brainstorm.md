---
title: "Measurement CLI — whole-cell + mask-based measurements"
date: 2026-02-19
status: complete
---

# Measurement CLI Brainstorm

## What We're Building

A CLI handler for menu item 5 "Measure channels" that supports two measurement modes:

1. **Whole-cell measurements** — the 7 standard metrics computed over each cell's full mask, for all channels. Auto-runs after segmentation and available as a manual menu item.

2. **Mask-based measurements** — the same 7 metrics computed over the portion of each cell that is inside or outside a binary threshold mask. Requires a threshold mask to exist (from menu item 6). Available as a manual menu item only.

Both modes store results in the same `measurements` table, distinguished by a new `scope` column.

## Why This Approach

- **Measure all channels at once**: PerCell 2 only measured what was needed for grouping. PerCell 3 takes advantage of the database — measure everything upfront so data is available for grouping, thresholding, reporting, and future features.
- **Scope column over prefix naming**: A `scope` column (`whole_cell`, `mask_inside`, `mask_outside`) is cleaner than metric name prefixes (`mask_inside_mean_intensity`). Same metric names work across all scopes, making queries and exports simpler.
- **Silent overwrite**: Measurements are cheap to recompute and always derived from images + labels. No confirmation needed.
- **Menu item for ad-hoc use**: Eventually a workflow orchestrator will chain steps automatically. For now, menu items provide manual control.

## Key Decisions

### 1. Two measurement modes in one menu item

Menu item 5 offers:
```
Measurement mode:
  [1] Whole cell (all channels, all metrics)
  [2] Inside threshold mask
  [3] Outside threshold mask
  [4] Both inside + outside mask
```

Options 2-4 require a threshold mask to exist and prompt the user to select which threshold channel/run to use.

### 2. Schema change: `scope` + `threshold_run_id` columns

Add to `measurements` table:
- `scope TEXT NOT NULL DEFAULT 'whole_cell'` — one of `whole_cell`, `mask_inside`, `mask_outside`
- `threshold_run_id INTEGER REFERENCES threshold_runs(id)` — nullable, set for mask-scoped measurements

The unique constraint becomes `(cell_id, channel_id, metric, scope)` to allow the same metric name across scopes.

### 3. Auto-measure whole-cell after segmentation

After `_segment_cells` completes, automatically run `BatchMeasurer` on all channels for the **newly segmented FOVs only** (not all FOVs in the experiment). Shows a progress bar and summary, consistent with segmentation output.

### 4. Channel selection varies by mode

- **Whole-cell mode**: All channels, no selection needed.
- **Mask mode**: One threshold mask at a time. User selects which threshold channel's mask to use. User then chooses which channels to measure against that mask (default: all channels). This enables cross-channel analysis (e.g., "how much UFD1L signal is inside GFP-positive regions").

### 5. Current 7 metrics are sufficient

- `mean_intensity`, `max_intensity`, `min_intensity`, `integrated_intensity`
- `std_intensity`, `median_intensity`, `area`

Ratios (inside/outside) are deferred to report generation, not stored as separate metrics.

### 6. Silent overwrite on re-measurement

`INSERT OR REPLACE` handles re-runs without user confirmation. The `scope` column ensures whole-cell and mask measurements don't collide.

### 7. Auto-measure feedback

Auto-measure after segmentation shows a progress bar (`Measuring FOV_001 [2/8]`) and a brief summary (`Measured 7 metrics x 3 channels for 1715 cells`). Consistent with segmentation progress output.

## Resolved Questions

- **Per-channel vs all-at-once?** → All channels at once for whole-cell. User-selectable for mask mode.
- **Metrics sufficient?** → Yes, 7 built-in metrics cover standard analysis. Percentile and shape metrics can be added later via plugins.
- **Re-measurement UX?** → Silent overwrite. Measurements are derived data.
- **Auto vs manual?** → Both. Auto whole-cell after segmentation + manual menu item for both modes.
- **Metric naming?** → Scope column, not prefixes. Cleanest and most versatile.
- **Mask measurement timing?** → Manual menu item only. Workflow orchestrator will automate later.
- **Auto-measure scope?** → Only newly segmented FOVs, not all FOVs in experiment.
- **Multiple masks?** → One mask at a time. Run menu item again for a different mask.
- **Cross-channel mask measurement?** → User chooses which channels to measure against the mask. Default: all channels.
- **Auto-measure feedback?** → Progress bar + summary. Not silent.

## Open Questions

(none)
