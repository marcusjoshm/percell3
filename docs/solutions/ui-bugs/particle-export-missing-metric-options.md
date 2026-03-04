---
title: "Particle CSV export missing metric columns in CLI filter"
date: 2026-03-03
category: ui-bugs
component: cli/menu.py
symptoms:
  - "Particle metric filter in export menu missing area_pixels, eccentricity, solidity, major/minor axis length"
  - "Users cannot select area_pixels for particle export despite column existing in data"
  - "Mismatch between selectable metrics in CLI and columns in export_particles_csv()"
root_cause: "Hardcoded particle_metric_options list in _export_csv() was manually maintained and fell out of sync with geom_metric_cols in export_particles_csv()"
severity: medium
tags:
  - particle-analysis
  - csv-export
  - cli-menu
  - hardcoded-list-drift
---

# Particle CSV Export Missing Metric Options

## Problem

The particle metric filter in the CLI export menu (`Data > Export to CSV`) only showed 6 options:

```
  [1] area_um2
  [2] perimeter
  [3] circularity
  [4] mean_intensity
  [5] max_intensity
  [6] integrated_intensity
```

But the actual particle data contains 11 metric columns. Users could not select `area_pixels`, `eccentricity`, `solidity`, `major_axis_length`, or `minor_axis_length` -- even though `export_particles_csv()` fully supports them.

## Root Cause

Two independent lists defined the same set of metrics:

1. **CLI filter** (`menu.py:~3230`): `particle_metric_options` -- hardcoded subset shown to users
2. **Export function** (`experiment_store.py`): `geom_metric_cols` -- authoritative list of available columns

These were written at different times and never kept in sync. When `area_pixels` and the morphology metrics were added to `geom_metric_cols`, the CLI list was not updated.

## Solution

### Before

```python
# src/percell3/cli/menu.py - _export_csv()
particle_metric_options = [
    "area_um2", "perimeter", "circularity",
    "mean_intensity", "max_intensity", "integrated_intensity",
]
```

### After

```python
particle_metric_options = [
    "area_pixels", "area_um2", "perimeter", "circularity",
    "eccentricity", "solidity", "major_axis_length", "minor_axis_length",
    "mean_intensity", "max_intensity", "integrated_intensity",
]
```

### Files Changed

- `src/percell3/cli/menu.py` -- Added missing metrics to `particle_metric_options` in `_export_csv()`

## Prevention

### Pattern: Hardcoded List Drift

This is a recurring anti-pattern in the codebase where a UI layer maintains its own copy of domain data instead of deriving it from the authoritative source. Other known instances:

- `todos/133-pending-p3-hardcoded-particle-metric-names.md` -- metric names hardcoded in query functions
- `todos/055-complete-p2-stale-model-names-cli-menu.md` -- Cellpose model names hardcoded in CLI

### How to Avoid

The most practical fix for this codebase: when adding a new metric to `geom_metric_cols` in `export_particles_csv()`, also update `particle_metric_options` in `_export_csv()`. A comment cross-referencing the two locations would help:

```python
# Keep in sync with geom_metric_cols in export_particles_csv()
particle_metric_options = [...]
```

A longer-term fix would be to derive the CLI options from the export function dynamically, but the current approach works if the coupling is documented.

## Related

- `todos/133-pending-p3-hardcoded-particle-metric-names.md`
- `docs/solutions/architecture-decisions/cli-module-code-review-findings.md` (Finding #021)
