---
title: Threshold Pair Filter for CSV Export
date: 2026-03-08
module: cli
problem_type: architecture-decision
tags: [csv-export, threshold-filtering, paired-cells, decapping-workflow, data-quality]
severity: info
reference_commit: 634ef2f
---

# Threshold Pair Filter for CSV Export

## Problem

Decapping sensor experiments produce cells with multiple threshold measurements (e.g., multiple P-body thresholds and multiple dilute-phase thresholds). For downstream statistical analysis, only matched pairs are valid: each cell should contribute exactly one P-body threshold row and one dilute-phase threshold row. Cells with mismatched counts (e.g., signal in only one threshold but not another) need to be excluded.

Additionally, rows where the mask-inside area is zero indicate that a threshold mask did not overlap with the cell at all -- these measurements are meaningless and should be dropped before pairing.

## Solution

A two-step filter that produces a clean paired dataset:

1. **Drop zero-area rows:** Remove any row where `{channel}_area_mask_inside == 0`, meaning the threshold mask had no overlap with the cell.
2. **Keep paired cells only:** Count remaining rows per `cell_id` and keep only cells with exactly 2 rows (one per threshold).

### Filter Logic

```python
# Step 1: Drop rows with no mask overlap
area_col = f"{channel}_area_mask_inside"
nonzero = pivot[pivot[area_col] > 0].copy()

# Step 2: Keep only cells appearing exactly twice
cell_counts = nonzero["cell_id"].value_counts()
paired_cells = set(cell_counts[cell_counts == 2].index)
filtered = nonzero[nonzero["cell_id"].isin(paired_cells)].copy()
```

## Where It Appears

The threshold pair filter is implemented in two locations in `src/percell3/cli/menu.py`:

### 1. Decapping Workflow Step 11 (Automatic)

In `_decapping_sensor_workflow()`, step 11 automatically applies the filter to all BG-subtracted FOVs after threshold assignment and auto-measurement. The filter channel is the BG subtraction channel selected at the start of the workflow. The filtered CSV is written to `exports/filtered_measurements_{timestamp}.csv` inside the experiment directory.

This step is fully automatic -- no user interaction required after step 10 completes.

### 2. Generic CSV Export (Optional)

The `_offer_threshold_dedup_filter()` function is called after every standard "Export to CSV" operation. It checks whether the exported data contains threshold information and `area_mask_inside` columns. If so, it offers the user an optional post-export filter:

- The user chooses whether to apply the filter (default: No)
- If multiple channels have `area_mask_inside` columns, the user selects which channel to filter on
- The filtered CSV is saved alongside the original with a `_filtered` suffix
- If the filtered file already exists, the user is asked before overwriting

### Differences Between the Two Locations

| Aspect | Decapping Step 11 | Generic Export |
|--------|-------------------|----------------|
| Trigger | Automatic | User opt-in |
| Channel selection | BG subtraction channel (from workflow params) | User-selected from available channels |
| Output path | `exports/filtered_measurements_{timestamp}.csv` | `{original_path}_filtered.csv` |
| Overwrite behavior | Always writes (timestamped name) | Prompts before overwriting |
| Data source | BG-subtracted FOVs only | Whatever FOVs were selected for export |

## Output Format

Both paths write provenance-annotated CSVs:

```
# experiment: /path/to/experiment.percell
# exported: 2026-03-07 14:30:00
# Filtered on GFP_area_mask_inside > 0, paired cell_ids (45/60 cells)
cell_id,fov_id,condition,...
```

The provenance header lines (prefixed with `#`) record the filter parameters and the ratio of kept-to-total cells for reproducibility.

## Related Documentation

- [NaN-Zero Plugin and NaN-Safe Metrics](nan-zero-plugin-and-nan-safe-metrics.md) -- Zero-pixel handling for derived FOV measurements
- [Run-Scoped Architecture Refactor](run-scoped-architecture-refactor-learnings.md) -- Scope-based measurements (mask_inside/mask_outside)
