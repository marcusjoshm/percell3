---
title: "Measurement CLI gap blocks thresholding workflow"
category: design-gaps
date: 2026-02-19
modules: [measure, cli]
tags: [measurement, thresholding, cli, dependency]
severity: blocking
---

# Measurement CLI Gap Blocks Thresholding Workflow

## Problem

Menu item 6 "Apply threshold" requires per-cell measurements to exist before
CellGrouper can group cells by expression level. Menu item 5 "Measure channels"
is disabled (`enabled=False`, `handler=None`), so users cannot create measurements
through the CLI. This creates a dead-end: thresholding is reachable but always
fails with "No measurements for metric ... Run measurements first."

## Root Cause

The measurement **backend** is fully implemented and tested:

| Component | Status | Location |
|-----------|--------|----------|
| `Measurer.measure_fov()` | Complete | `src/percell3/measure/measurer.py` |
| `Measurer.measure_cells()` (preview) | Complete | `src/percell3/measure/measurer.py` |
| `MetricRegistry` (7 built-in metrics) | Complete | `src/percell3/measure/metrics.py` |
| `BatchMeasurer.measure_experiment()` | Complete | `src/percell3/measure/batch.py` |
| `store.add_measurements()` | Complete | `src/percell3/core/experiment_store.py` |
| `store.get_measurements()` | Complete | `src/percell3/core/experiment_store.py` |
| `store.get_measurement_pivot()` | Complete | `src/percell3/core/experiment_store.py` |
| `measurements` table + indexes | Complete | `src/percell3/core/schema.py` |
| Tests (17 tests) | Complete | `tests/test_measure/test_measurer.py`, `test_batch.py` |
| **CLI handler `_measure_channels`** | **Missing** | `src/percell3/cli/menu.py` |

The only missing piece is the CLI handler function and enabling the menu item.

## Secondary Issue: Metric Name Bug

`_apply_threshold` (menu item 6) presents `"total_intensity"` as a grouping
metric option, but the registered metric name is `"integrated_intensity"`.
If selected, CellGrouper fails with the same "No measurements" error even
when measurements have been run.

**Fix applied:** Changed `"total_intensity"` to `"integrated_intensity"` in
the metrics list at `menu.py:885`.

## What the CLI Handler Needs

The `_measure_channels` handler should follow the same pattern as `_segment_cells`:

1. Guard: require loaded experiment, channels, and segmented cells
2. Channel selection (multi-select or "all")
3. Metric selection (default: all 7, or user subset)
4. FOV selection (reuse existing table-based selector)
5. Confirmation summary
6. Run `BatchMeasurer.measure_experiment()` with progress callback
7. Print `BatchResult` summary

## Impact

- Thresholding (menu item 6) is unusable for channel-based metrics
- Grouping by `area_pixels` still works (reads from cells table directly)
- The measurement backend is solid; only CLI wiring is needed

## Resolution

Implement `_measure_channels` handler, enable menu item 5, and add a
prerequisite check in `_apply_threshold` that warns early if measurements
don't exist for the selected channel/metric combination.
