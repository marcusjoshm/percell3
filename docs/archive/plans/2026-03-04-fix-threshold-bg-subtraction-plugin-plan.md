---
title: "fix: Threshold BG subtraction separate histogram/apply FOVs"
type: fix
date: 2026-03-04
brainstorm: docs/brainstorms/2026-03-04-fix-threshold-bg-subtraction-plugin-brainstorm.md
---

# fix: Threshold BG Subtraction — Separate Histogram/Apply FOVs

## Overview

Fix the `ThresholdBGSubtractionPlugin` to separate "histogram source" FOVs (dilute-phase controls used to estimate background) from "apply" FOVs (full images where subtraction is applied). Also fix sparse derived FOVs (copy ALL channels), add fov_config inheritance, and add matplotlib as a required dependency.

## Issues Being Fixed

1. **Wrong workflow** — Currently histogram and subtraction use the same FOV set. Real usage: dilute-phase FOVs provide the histogram; full-image FOVs receive the subtraction.
2. **Sparse derived FOV** — Currently only writes the subtracted channel. Should copy ALL channels from the apply FOV so derived FOVs are full citizens.
3. **Missing config inheritance** — Derived FOV only gets fresh `whole_field` segmentation from `add_fov`. Should inherit the apply FOV's full `fov_config` (segmentation + threshold entries).
4. **Missing matplotlib dependency** — `render_peak_histogram` fails silently because matplotlib is not in `pyproject.toml`.

## Proposed Solution

### New CLI Workflow (menu.py)

```
Step 1: Select channel (for both histogram and subtraction)
Step 2: Select "histogram FOVs" — filtered to FOVs with configured thresholds
Step 3: For EACH histogram FOV, prompt user to select the "apply FOV"
        — from all other FOVs (not the histogram FOV itself)
Step 4: Confirmation summary showing all pairings
Step 5: Execute + summary table
```

Example Step 3 interaction:
```
Histogram FOV 1 of 2: TL2_dilute_phase_As_FOV_001
  Select the FOV to apply background subtraction to:
  [1] As_WT_1A-Dcp2_Sensor_N1_FOV_001
  [2] UT_WT_1A-Dcp2_Sensor_N1_FOV_001
  ...
Apply FOV (h=home, b=back): 1
```

### New Plugin Parameters

```python
# Old:
parameters = {"channel": "ch00", "fov_ids": [1, 2]}

# New:
parameters = {
    "channel": "ch00",
    "pairings": [
        {"histogram_fov_id": 14, "apply_fov_id": 5},
        {"histogram_fov_id": 15, "apply_fov_id": 12},
    ],
}
```

### Plugin Run Logic (per pairing)

```
For each pairing (histogram_fov_id, apply_fov_id):
  1. Load channel image from histogram FOV
  2. Get configured thresholds from histogram FOV's fov_config
  3. For each threshold:
     a. Load mask from threshold
     b. Extract masked pixels from histogram FOV's channel image
     c. find_gaussian_peaks(masked_pixels) → bg_value
     d. Load ALL channel images from apply FOV
     e. Build derived image for the selected channel:
        subtracted = clip(apply_image.int32 - bg_value, 0, max)
        derived = where(mask_bool, subtracted, 0).astype(source_dtype)
     f. Create derived FOV named: {apply_fov}_bgsub_{threshold_name}_{channel}
     g. Write ALL channels: subtracted channel + copy of other channels from apply FOV
     h. Copy fov_config entries from apply FOV to derived FOV
     i. Save histogram PNG
```

### Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Histogram source pixels | Threshold-masked pixels only | Thresholds define relevant cell populations |
| Pairing method | User manually selects per histogram FOV | Simple, no fragile name-matching heuristics |
| Multi-threshold behavior | One derived FOV per threshold | Each threshold subpopulation needs separate background estimate |
| Derived FOV channels | Full copy from apply FOV | Derived FOVs are full citizens, can be segmented/measured |
| Config inheritance | Copy all fov_config entries from apply FOV | Derived FOVs inherit segmentation + threshold settings |
| Derived FOV naming | `{apply_fov}_bgsub_{threshold_name}_{channel}` | Apply FOV name only; threshold name implies histogram source |
| Unmasked pixels in subtracted channel | Zeroed | Standard for background subtraction — signal only where mask is |
| Matplotlib | Required dependency in pyproject.toml | Histograms are core output, not optional |

## Implementation Plan

### Phase 1: Add matplotlib dependency

- [x] Add `matplotlib` to `pyproject.toml` dependencies list

**File:** `pyproject.toml`

### Phase 2: Update plugin parameters and run logic

- [x] Change `get_parameter_schema` to accept `pairings` instead of `fov_ids`
- [x] Rewrite `run()` to iterate over pairings (histogram FOV → apply FOV)
- [x] In `_process_threshold`: load histogram FOV image for peak detection, load apply FOV images for output
- [x] Copy ALL channels from apply FOV to derived FOV (subtracted channel replaced, others copied verbatim)
- [x] After creating derived FOV, copy fov_config entries from apply FOV

**File:** `src/percell3/plugins/builtin/threshold_bg_subtraction.py`

Channel copy pattern (from ImageCalculatorPlugin):
```python
channels = store.get_channels()
for ch in channels:
    if ch.name == channel:
        store.write_image(derived_fov_id, ch.name, derived_image)
    else:
        ch_image = store.read_image_numpy(apply_fov_id, ch.name)
        store.write_image(derived_fov_id, ch.name, ch_image)
```

Config inheritance pattern:
```python
apply_config = store.get_fov_config(apply_fov_id)
for entry in apply_config:
    store.set_fov_config_entry(
        derived_fov_id,
        entry.segmentation_id,
        threshold_id=entry.threshold_id,
        scopes=entry.scopes,
    )
```

### Phase 3: Update CLI handler

- [x] Step 2: filter FOVs to those with thresholds (histogram FOVs) — same as current
- [x] Step 3: for each selected histogram FOV, prompt `numbered_select_one` to pick apply FOV from remaining FOVs
- [x] Step 4: show pairing summary before confirmation
- [x] Build `pairings` list and pass to plugin

**File:** `src/percell3/cli/menu.py` — `_run_threshold_bg_subtraction()`

### Phase 4: Update tests

- [x] Update fixture to create TWO FOVs: one histogram (with threshold), one apply (no threshold)
- [x] Update `test_creates_derived_fov` to use pairings parameter
- [x] Update `test_derived_fov_inherits_metadata` to verify metadata comes from apply FOV
- [x] Update `test_derived_image_correct` — histogram FOV provides bg estimate, apply FOV provides image
- [x] Add `test_derived_fov_has_all_channels` — verify all channels from apply FOV are present
- [x] Add `test_derived_fov_inherits_fov_config` — verify fov_config entries copied from apply FOV
- [x] Update `test_no_underflow_on_uint16` with new parameter format
- [x] Update `test_idempotent_rerun` with new parameter format
- [x] Update `test_empty_mask_produces_warning` with new parameter format
- [x] Update `test_histogram_png_saved` with new parameter format
- [x] Update `test_progress_callback` with new parameter format
- [x] Update `test_derived_fov_can_be_deleted` with new parameter format
- [x] Update `test_requires_parameters` with new parameter format

**File:** `tests/test_plugins/test_threshold_bg_subtraction.py`

## Acceptance Criteria

- [ ] Plugin accepts `pairings` parameter with `histogram_fov_id` and `apply_fov_id` per entry
- [ ] Background is estimated from histogram FOV's masked pixels
- [ ] Subtraction is applied to apply FOV's channel image
- [ ] Derived FOV contains ALL channels from apply FOV (not just subtracted channel)
- [ ] Derived FOV inherits fov_config entries from apply FOV
- [ ] Derived FOV named `{apply_fov}_bgsub_{threshold_name}_{channel}`
- [ ] CLI prompts for histogram FOVs, then per-histogram prompts for apply FOV
- [ ] matplotlib is a declared dependency in pyproject.toml
- [ ] All existing test scenarios pass with updated parameter format
- [ ] Idempotent re-runs still work (reuse derived FOV by name)

## References

### Internal Patterns
- Channel copy: `src/percell3/plugins/builtin/image_calculator.py:167-194`
- fov_config entry: `src/percell3/core/models.py:110-119` (FovConfigEntry dataclass)
- set_fov_config_entry: `src/percell3/core/experiment_store.py:1021`
- CLI numbered_select_one: `src/percell3/cli/menu.py:108`
- CLI _select_fovs_from_table: `src/percell3/cli/menu.py:1515`

### Learnings Applied
- `docs/solutions/architecture-decisions/image-calculator-plugin-architecture.md` — derived FOV full channel copy pattern
- `docs/solutions/architecture-decisions/run-scoped-architecture-refactor-learnings.md` — fov_config inheritance via set_fov_config_entry
