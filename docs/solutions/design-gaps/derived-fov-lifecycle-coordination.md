---
title: "Derived FOV lifecycle: cell duplication, auto-measurement, and NaN-safe metrics"
problem_type: design-gaps
component: plugins/nan_zero, measure/metrics, cli/menu
symptoms:
  - "RuntimeWarning: invalid value encountered in cast when writing NaN float32 to integer-dtype zarr array"
  - "CSV export shows source FOV name instead of derived FOV name"
  - "CSV export completely empty after cell duplication fix"
  - "NaN pixels propagate through np.mean, making all measurements NaN"
resolution_date: "2026-03-07"
confidence: high
tags:
  - derived-fov
  - zarr-dtype
  - cell-duplication
  - auto-measurement
  - nan-safe-metrics
  - plugin-architecture
---

# Derived FOV Lifecycle Coordination

## Problem

When creating the `nan_zero` plugin (replace zero pixels with NaN to exclude
them from `np.nanmean`), four cascading bugs revealed a design gap: creating
a **derived FOV** (pixel transformation producing a new FOV) requires four
coordinated steps, and missing any step produces subtle downstream failures.

## The Four-Step Derived FOV Contract

Any plugin that creates a derived FOV must complete ALL of these steps for the
FOV to be fully functional (measurable + exportable):

| Step | What | Why |
|------|-------|-----|
| 1 | Create FOV + write channels | Pixel data exists in zarr |
| 2 | Copy `fov_config` entries | Segmentation + threshold assignments linked |
| 3 | Duplicate cell records | `get_cells(fov_id=derived)` returns cells |
| 4 | Run measurements | Measurements exist for derived cell IDs |

The existing `image_calculator` plugin only did steps 1-2, which has the same
latent bug (unmeasurable derived FOVs).

## Bug 1: Zarr Dtype Mismatch

**Symptom:** `RuntimeWarning: invalid value encountered in cast`

**Root cause:** The zarr array dtype is determined by the first channel write.
If an unselected channel (integer dtype) was written first, the array was
created as integer. Subsequent float32 NaN writes were cast to integer, losing
NaN values silently.

**Fix:** Cast ALL channels to float32, not just selected ones:

```python
# Before (bug): only selected channels cast to float32
for ch in all_channels:
    image = store.read_image_numpy(fov_id, ch.name)
    if ch.name in target_channels:
        image = image.astype(np.float32)
        image[image == 0] = np.nan
    store.write_image(derived_fov_id, ch.name, image)

# After (fix): uniform float32 dtype for all channels
for ch in all_channels:
    image = store.read_image_numpy(fov_id, ch.name)
    image = image.astype(np.float32)  # always float32
    if ch.name in target_channels:
        image[image == 0] = np.nan
    store.write_image(derived_fov_id, ch.name, image)
```

**File:** `src/percell3/plugins/builtin/nan_zero.py`

## Bug 2: Wrong FOV Name in CSV Export

**Symptom:** CSV `fov_name` column showed the source FOV name, not the derived.

**Root cause:** Cells have `fov_id` pointing to the source FOV (where
segmentation ran). The CSV pivot joins `cells.fov_id -> fovs.id` to get
`fov_name`. Without cell records for the derived FOV, the pivot resolves to
the source FOV name.

**Fix:** Duplicate cell records from source to derived FOV:

```python
source_cells = store.get_cells(fov_id=source_fov_id, is_valid=False)
records = [
    CellRecord(
        fov_id=derived_fov_id,  # point to derived FOV
        segmentation_id=row["segmentation_id"],
        label_value=row["label_value"],
        # ... copy all spatial properties
    )
    for _, row in source_cells.iterrows()
]
store.add_cells(records)
```

**File:** `src/percell3/plugins/builtin/nan_zero.py`

## Bug 3: Empty CSV After Cell Duplication

**Symptom:** CSV was completely empty after adding cell duplication.

**Root cause:** Duplicated cells get new auto-increment IDs from SQLite. No
measurements existed for these new IDs. The measurement pivot found cells but
zero measurements, producing an empty DataFrame.

**Fix:** Auto-measure the derived FOV immediately after cell duplication:

```python
def _measure_derived_fov(store, fov_id, config):
    measurer = Measurer()
    for entry in config:
        measurer.measure_fov(store, fov_id, channels, entry.segmentation_id)
        if entry.threshold_id is not None:
            measurer.measure_fov_masked(
                store, fov_id, channels,
                segmentation_id=entry.segmentation_id,
                threshold_id=entry.threshold_id,
                scopes=[s for s in entry.scopes if s in ("mask_inside", "mask_outside")],
            )
```

**File:** `src/percell3/plugins/builtin/nan_zero.py`

## Bug 4: NaN Propagation in Metrics

**Symptom:** Even with measurements running, all values were NaN because
`np.mean` propagates NaN.

**Root cause:** All 6 built-in intensity metrics used NaN-propagating numpy
functions. A single NaN pixel in a cell mask made the entire metric NaN.

**Fix:** Switch to NaN-safe variants in `src/percell3/measure/metrics.py`:

| Before | After |
|--------|-------|
| `np.mean` | `np.nanmean` |
| `np.max` | `np.nanmax` |
| `np.min` | `np.nanmin` |
| `np.sum` | `np.nansum` |
| `np.std` | `np.nanstd` |
| `np.median` | `np.nanmedian` |

The `area` metric (operates on boolean mask) was unchanged.

**Note:** This is a safe change for all FOVs. When no NaN values are present,
`np.nanmean` behaves identically to `np.mean`.

## Prevention: Derived FOV Helper

Future derived-FOV plugins should follow the complete 4-step pattern. Consider
extracting a shared helper:

```python
def create_measurable_derived_fov(store, source_fov_id, derived_fov_id):
    """Steps 2-4 of the derived FOV contract."""
    # Step 2: copy config
    for entry in store.get_fov_config(source_fov_id):
        store.set_fov_config_entry(derived_fov_id, entry.segmentation_id, ...)
    # Step 3: duplicate cells
    source_cells = store.get_cells(fov_id=source_fov_id, is_valid=False)
    store.add_cells([CellRecord(fov_id=derived_fov_id, ...) for cell in source_cells])
    # Step 4: auto-measure
    _measure_derived_fov(store, derived_fov_id, config)
```

## Related Documentation

- [Image Calculator Plugin Architecture](../architecture-decisions/image-calculator-plugin-architecture.md) — same derived FOV pattern, has latent step 3-4 gap
- [Measurement CLI and Threshold Prerequisites](measurement-cli-and-threshold-prerequisites.md) — measurement pipeline prerequisites

## Files Changed

- `src/percell3/plugins/builtin/nan_zero.py` (new) — plugin with full 4-step lifecycle
- `src/percell3/measure/metrics.py` — NaN-safe metric functions
- `src/percell3/cli/menu.py` — `_run_nan_zero` interactive handler
