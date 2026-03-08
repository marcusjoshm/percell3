---
title: "feat: Add Image Calculator Plugin"
type: feat
date: 2026-03-02
brainstorm: docs/brainstorms/2026-03-02-image-calculator-plugin-brainstorm.md
---

# feat: Add Image Calculator Plugin

## Overview

An Image Calculator plugin modeled after ImageJ's `Process > Math` and `Process > Image Calculator` features. Operates on a single FOV at a time with two modes: single-channel math (apply a constant) and two-channel math (operate between two channels). All operations are non-destructive, producing a new derived FOV.

## Problem Statement / Motivation

Users need to perform pixel-level arithmetic on microscopy images — background subtraction with a constant, ratio imaging between channels, difference imaging, etc. ImageJ provides this through two separate menus (`Process > Math` and `Process > Image Calculator`). Having this as a PerCell 3 plugin keeps users in the experiment workflow without exporting to ImageJ and re-importing.

## Proposed Solution

A single `AnalysisPlugin` subclass with a `mode` parameter that switches between single-channel and two-channel operation. Follows the established split_halo pattern for derived FOV creation.

### Operations

| Operation | Single-channel (with constant) | Two-channel (between channels) |
|-----------|-------------------------------|-------------------------------|
| Add       | pixel + constant              | pixelA + pixelB               |
| Subtract  | pixel - constant              | pixelA - pixelB               |
| Multiply  | pixel * constant              | pixelA * pixelB               |
| Divide    | pixel / constant              | pixelA / pixelB               |
| AND       | pixel & int(constant)         | pixelA & pixelB               |
| OR        | pixel \| int(constant)        | pixelA \| pixelB              |
| XOR       | pixel ^ int(constant)         | pixelA ^ pixelB               |
| Min       | min(pixel, constant)          | min(pixelA, pixelB)           |
| Max       | max(pixel, constant)          | max(pixelA, pixelB)           |
| Abs Diff  | abs(pixel - constant)         | abs(pixelA - pixelB)          |

### Output: Derived FOV

Both modes create a derived FOV via `store.add_fov()` + `store.write_image()`, following the split_halo pattern.

**Design consideration — channel naming:** Channels are global entities in PerCell 3 (shared across all FOVs). Creating new channel names (e.g., `ch00_add_50`) would pollute the global namespace and create empty slots on unrelated FOVs. Instead, the recommended approach is:

- **Write the computed result to `channel_a`'s existing slot** on the derived FOV.
- **For two-channel mode:** zero out `channel_b`'s slot (it was consumed by the operation).
- **Copy all other channels unchanged.**
- **The derived FOV's `display_name` describes the operation** (e.g., `sample_01_ch00_multiply_ch01`).

This follows the split_halo pattern exactly — write to existing channel slots, use FOV naming for context.

**Single-channel example** (Add 50 to ch00, 3-channel FOV `sample_01`):
- Derived FOV: `sample_01_ch00_add_50`
- ch00 slot → computed (ch00 + 50, clipped)
- ch01 slot → copied unchanged
- ch02 slot → copied unchanged

**Two-channel example** (Multiply ch00 by ch01, 3-channel FOV `sample_01`):
- Derived FOV: `sample_01_ch00_multiply_ch01`
- ch00 slot → computed (ch00 * ch01, clipped)
- ch01 slot → zeros (consumed)
- ch02 slot → copied unchanged

### Data Type Handling

- Intermediate computation in `float64` to avoid overflow during calculation.
- Final result clipped to the original image dtype range (e.g., 0–65535 for uint16) and cast back.
- Division by zero produces 0 (use `np.where` or `np.divide` with `where` parameter).
- Bitwise operations (AND, OR, XOR) require integer types — if the image is float, cast to int first or raise a validation error.

## Technical Considerations

### Architecture

- Plugin class in `src/percell3/plugins/builtin/image_calculator.py`.
- Pure computation functions in `src/percell3/plugins/builtin/image_calculator_core.py` (numpy only, no store dependency). Follows the `bg_subtraction_core.py` pattern.
- Tests in `tests/test_plugins/test_image_calculator.py`.

### Hexagonal Boundary

- Only use `ExperimentStore` public API — never access `store._conn` or import `queries`.
- Methods needed: `get_channels()`, `get_fovs()`, `get_fov_by_id()`, `read_image_numpy()`, `write_image()`, `add_fov()`.

### Idempotent Re-runs

Follow the split_halo pattern: before creating a derived FOV, check if one with the same `display_name` already exists. If so, overwrite its images instead of creating a duplicate.

```python
existing_fov_map = {f.display_name: f.id for f in store.get_fovs()}
if derived_name in existing_fov_map:
    derived_fov_id = existing_fov_map[derived_name]
else:
    derived_fov_id = store.add_fov(...)
```

### No `required_inputs()`

This plugin does NOT require segmentation or thresholds. Return `[]` from `required_inputs()`. It operates purely on channel images.

## Acceptance Criteria

### Phase 1: Core Math Engine (`image_calculator_core.py`)

- [x] `apply_single_channel(image, operation, constant) -> np.ndarray` function
  - Accepts a 2D numpy array, operation name, and constant value
  - Computes in float64, clips to input dtype, returns same-dtype result
  - Handles division by zero → 0
  - All 10 operations work correctly
- [x] `apply_two_channel(image_a, image_b, operation) -> np.ndarray` function
  - Accepts two 2D numpy arrays and operation name
  - Same float64 intermediate → clip → cast pattern
  - Handles division by zero → 0
  - All 10 operations work correctly
- [x] Bitwise operations (AND, OR, XOR) validate integer input types
- [x] Unit tests for core math functions covering:
  - Each operation with known inputs/outputs
  - Overflow clipping (e.g., uint16 add that exceeds 65535)
  - Underflow clipping (e.g., uint16 subtract that goes below 0)
  - Division by zero
  - Bitwise ops on integer images

### Phase 2: Plugin Class (`image_calculator.py`)

- [x] `ImageCalculatorPlugin` subclass of `AnalysisPlugin`
- [x] `info()` returns `PluginInfo(name="image_calculator", version="1.0.0", ...)`
- [x] `required_inputs()` returns `[]`
- [x] `validate(store)` checks:
  - At least one channel exists
  - At least one FOV exists
- [x] `get_parameter_schema()` returns JSON Schema with:
  - `mode`: `"single_channel"` | `"two_channel"` (required)
  - `operation`: enum of 10 operations (required)
  - `fov_id`: integer (required)
  - `channel_a`: string (required)
  - `channel_b`: string (required for two_channel mode, ignored for single_channel)
  - `constant`: number (required for single_channel mode, ignored for two_channel)
- [x] `run()` method:
  - Validates mode-specific required parameters at runtime (channel_b for two_channel, constant for single_channel)
  - Validates that specified channels and FOV exist
  - Reads source images via `store.read_image_numpy()`
  - Calls core math functions
  - Creates derived FOV with descriptive `display_name`
  - Writes computed result to `channel_a` slot
  - For two-channel: zeros `channel_b` slot
  - Copies all other channels unchanged
  - Handles idempotent re-runs (overwrite existing derived FOV by name)
  - Calls `progress_callback` if provided
  - Returns `PluginResult` with `cells_processed=0`, `measurements_written=0`, appropriate `custom_outputs`

### Phase 3: Tests (`test_image_calculator.py`)

- [x] `_create_calculator_experiment(tmp_path)` helper — 2+ channels, 1+ FOV with known pixel values
- [x] `TestPluginInfo` — info(), parameter schema, required_inputs
- [x] `TestValidation` — empty experiment, no channels, no FOVs, valid experiment
- [x] `TestSingleChannelMath` — each operation with constant, verify derived FOV pixel values
- [x] `TestTwoChannelMath` — each operation between channels, verify result and channel_b zeroed
- [x] `TestDerivedFOVCreation` — FOV naming, metadata inheritance, channel copying, idempotent re-run
- [x] `TestEdgeCases` — division by zero, overflow/underflow clipping, same channel for both inputs, progress callback

## Dependencies & Risks

**Dependencies:**
- `ExperimentStore` public API — all needed methods already exist
- `numpy` — already a project dependency

**Risks:**
- **Global channel namespace:** If we later decide to create new channel names for computed results, the global channel architecture would need careful handling. The current plan avoids this by writing to existing channel slots.
- **Large images:** Float64 intermediate doubles memory usage. For very large FOVs this could be significant, but single-FOV processing limits the blast radius.

## References & Research

### Internal References
- Split halo plugin (derived FOV pattern): `src/percell3/plugins/builtin/split_halo_condensate_analysis.py:455`
- Plugin base class: `src/percell3/plugins/base.py`
- Plugin registry: `src/percell3/plugins/registry.py`
- Core math separation pattern: `src/percell3/plugins/builtin/bg_subtraction_core.py`
- ExperimentStore API: `src/percell3/core/experiment_store.py`
- Plugin test pattern: `tests/test_plugins/test_split_halo_condensate_analysis.py`

### Institutional Learnings Applied
- Hexagonal boundary enforcement (`docs/solutions/architecture-decisions/segment-module-private-api-encapsulation-fix.md`)
- Layer-based architecture (`docs/solutions/architecture-decisions/layer-based-architecture-redesign-learnings.md`)
- Write-Invalidate-Cleanup pattern (`docs/solutions/database-issues/zarr-sqlite-state-mismatch-re-thresholding.md`)

### Brainstorm
- `docs/brainstorms/2026-03-02-image-calculator-plugin-brainstorm.md`
