---
title: "Fix Threshold Background Subtraction Plugin"
date: 2026-03-04
type: fix
status: brainstorm
---

# Fix Threshold Background Subtraction Plugin

## What We're Building

A corrected version of `ThresholdBGSubtractionPlugin` that fixes the workflow and derived FOV quality. The key change: **separate the "histogram source" FOVs from the "apply subtraction" FOVs**.

### Real-World Scenario

In fluorescence microscopy, dilute-phase FOVs contain only background signal (no condensates). The user wants to:
1. Estimate background from the dilute-phase image histogram (using threshold masks)
2. Subtract that background value from the original full-image FOVs

### New CLI Workflow

```
Step 1: Select channel (for both histogram and subtraction)
Step 2: Select "histogram FOVs" — the FOVs used to estimate background
         (filtered to FOVs with configured thresholds)
Step 3: For EACH histogram FOV, prompt user to select the "apply FOV"
         — the FOV that gets the subtraction applied
Step 4: Confirmation summary
Step 5: Execute + summary table
```

**Example interaction for Step 3:**
```
Histogram FOV 1 of 2: TL2_dilute_phase_As_FOV_001
  Select the FOV to apply background subtraction to:
  [1] As_WT_1A-Dcp2_Sensor_N1_FOV_001
  [2] UT_WT_1A-Dcp2_Sensor_N1_FOV_001
  ...
Apply FOV (h=home, b=back): 1

Histogram FOV 2 of 2: TL2_dilute_phase_UT_FOV_001
  Select the FOV to apply background subtraction to:
  [1] As_WT_1A-Dcp2_Sensor_N1_FOV_001
  [2] UT_WT_1A-Dcp2_Sensor_N1_FOV_001
  ...
Apply FOV (h=home, b=back): 2
```

## Why This Approach

- **Separating histogram/apply FOVs** matches the real experiment: dilute-phase images are controls used only for background estimation, while full images are where the subtraction matters.
- **User-driven pairing** (no automatic name matching) is simple and avoids fragile heuristics.
- **One prompt per histogram FOV** keeps the interaction clear and sequential.

## Key Decisions

1. **Histogram source**: Use threshold-masked pixels from the histogram FOV (not all pixels) — thresholds define the relevant cell populations
2. **Apply target**: User manually selects which FOV each histogram maps to (no auto-matching by name)
3. **Multi-threshold**: Each threshold on the histogram FOV produces a separate derived FOV from the apply FOV (e.g., g1 and g2 → 2 derived FOVs)
4. **Derived FOV is a full copy**: All channels copied from the apply FOV; only the selected channel is replaced with the background-subtracted version
5. **Inherit fov_config**: Derived FOV inherits segmentation AND threshold config entries from the apply FOV
6. **Naming**: `{apply_fov}_bgsub_{threshold_name}_{channel}` (apply FOV name only, threshold name implies histogram source)
7. **Matplotlib**: Make it a required dependency (add to pyproject.toml)
8. **Histogram PNGs**: Keep saving them to `exports/bgsub_histograms/`

## Issues Being Fixed

1. **Wrong workflow**: Currently histogram and subtraction both use the same FOV set — needs to be separate selections
2. **Sparse derived FOV**: Currently only writes the subtracted channel — should copy ALL channels from the apply FOV
3. **Missing config inheritance**: Derived FOV only gets fresh whole_field segmentation — should inherit the apply FOV's full fov_config (segmentation + threshold entries)
4. **Missing matplotlib**: `render_peak_histogram` fails silently — add matplotlib as a required dependency
5. **Delete derived FOV crash**: Already fixed in previous commit (`.DS_Store` race in `shutil.rmtree`)

## Open Questions

None — all questions resolved during brainstorm.
