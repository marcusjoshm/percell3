---
title: NaN-Zero Plugin and NaN-Safe Metrics
date: 2026-03-07
module: plugins, measure
problem_type: architecture-decision
tags: [nan-safe, derived-fov, zero-pixels, measurement-accuracy, plugin-system]
severity: info
reference_commit: 18c1493
---

# NaN-Zero Plugin and NaN-Safe Metrics

## Problem

When measuring mean intensity in derived FOV channels (e.g., after split-halo analysis or background subtraction), zero-valued pixels skew measurements downward. These zeros do not represent true signal -- they are artifacts of masking or subtraction operations. Including them in `np.mean` produces incorrect per-cell intensity values because the zeros are counted in the denominator.

Example: A cell with 100 pixels where 60 have real signal (mean ~500) and 40 are masked zeros would report `np.mean` of ~300 instead of ~500.

## Solution

### 1. NaN-Zero Plugin (`nan_zero`)

A new `AnalysisPlugin` that creates derived FOVs where zero-valued pixels in selected channels are replaced with `np.nan`. All channels are cast to `float32` to support NaN values.

**Location:** `src/percell3/plugins/builtin/nan_zero.py`

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `fov_ids` | `list[int]` | FOV IDs to process |
| `channels` | `list[str]` | Channel names in which to replace zeros with NaN |
| `name_prefix` | `str` | Prefix for derived FOV names (default: `"nan_zero"`) |

**Core logic:**

```python
image = image.astype(np.float32)
if ch.name in target_channels:
    image[image == 0] = np.nan
```

### 2. NaN-Safe Metrics

All 7 built-in measurement metrics in `src/percell3/measure/metrics.py` were changed from standard numpy functions to their NaN-safe counterparts:

| Metric | Before | After |
|--------|--------|-------|
| `mean_intensity` | `np.mean` | `np.nanmean` |
| `max_intensity` | `np.max` | `np.nanmax` |
| `min_intensity` | `np.min` | `np.nanmin` |
| `integrated_intensity` | `np.sum` | `np.nansum` |
| `std_intensity` | `np.std` | `np.nanstd` |
| `median_intensity` | `np.median` | `np.nanmedian` |
| `area` | `np.sum(mask)` | `np.sum(mask)` (unchanged -- operates on boolean mask, not image) |

These changes are backward-compatible: NaN-safe functions behave identically to their standard counterparts when no NaN values are present.

## Derived FOV Contract

The nan_zero plugin follows the four-step derived FOV contract established by split-halo and other plugins:

1. **Create FOV + write channels** -- New FOV with `{prefix}_{source_name}` display name. All channels cast to float32; selected channels have zeros replaced with NaN.
2. **Copy fov_config** -- All segmentation and threshold assignments from the source FOV are duplicated onto the derived FOV.
3. **Duplicate cells** -- Cell records (with bounding boxes, centroids, morphology) are copied from source to derived FOV so the derived FOV has measurable cells.
4. **Auto-measure** -- `_measure_derived_fov()` runs whole-cell and masked measurements immediately, so the derived FOV is exportable without a separate measurement step.

Idempotent re-runs are supported: if a derived FOV with the expected display name already exists, it is reused rather than duplicated.

## Edge Cases

- **Cells with all-NaN pixels:** When every pixel in a cell's mask region is NaN (e.g., the entire cell was in a masked-out area), `np.nanmean` and similar functions return `NaN` and emit a `RuntimeWarning`. The NaN measurement value is stored in the database and propagates to CSV export.
- **Unselected channels:** Channels not listed in the `channels` parameter are still cast to float32 (for uniform dtype in the zarr array) but their zeros are preserved.
- **Re-run behavior:** If the derived FOV already exists, channels are overwritten but cells are only copied if no cells exist yet on the derived FOV.

## Related Documentation

- [Image Calculator Plugin Architecture](image-calculator-plugin-architecture.md) -- Another derived FOV plugin with similar patterns
- [Run-Scoped Architecture Refactor](run-scoped-architecture-refactor-learnings.md) -- Scope-based measurements (mask_inside/mask_outside/whole_cell)
