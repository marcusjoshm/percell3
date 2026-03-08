---
title: Image Calculator Plugin Architecture and Implementation
date: 2026-03-03
module: plugins
problem_type: architecture-decision
tags: [plugin-system, image-processing, derived-fovs, mathematical-operations, idempotency]
severity: info
---

# Image Calculator Plugin Architecture

## Problem

PerCell 3 needed ImageJ-like pixel arithmetic capabilities within its experiment workflow. Users needed to:
- Apply math operations with a constant to a single channel (ImageJ's `Process > Math`)
- Perform pixel-wise arithmetic between two channels (ImageJ's `Process > Image Calculator`)
- Keep results non-destructive (original FOVs preserved)
- Support 10 operations: add, subtract, multiply, divide, AND, OR, XOR, min, max, abs_diff

## Solution

A single `AnalysisPlugin` with two modes (`single_channel` and `two_channel`), using the established derived FOV pattern from `split_halo_condensate_analysis`.

### Files Created

| File | Purpose |
|------|---------|
| `src/percell3/plugins/builtin/image_calculator_core.py` | Pure numpy math (no store deps) |
| `src/percell3/plugins/builtin/image_calculator.py` | Plugin class (store I/O, FOV creation) |
| `tests/test_plugins/test_image_calculator.py` | 47 tests |

## Key Design Decisions

### 1. Core/Plugin Separation

Pure computation in `image_calculator_core.py`, store interaction in `image_calculator.py`. This follows the `bg_subtraction_core.py` pattern and makes the math independently testable.

### 2. Write to Existing Channel Slots (Not New Channels)

Channels are global entities in PerCell 3 (shared across all FOVs). Creating new channel names like `ch00_add_50` would pollute the global namespace and create empty slots on unrelated FOVs.

**Decision**: Write the computed result to `channel_a`'s existing slot in the derived FOV. Use the FOV's `display_name` to describe the operation.

### 3. Float64 Intermediate + Clip & Cast

```python
def _apply_op(a, b, operation):
    af = a.astype(np.float64)  # prevent overflow during computation
    # ... operation ...
    return result  # float64

def _clip_and_cast(result, target_dtype):
    lo, hi = _get_dtype_range(target_dtype)
    return np.clip(result, lo, hi).astype(target_dtype)
```

This prevents integer wrap (e.g., uint16 65500 + 100 = 65535, not 64).

### 4. Idempotent Re-runs via Display Name

```python
derived_name = f"{fov_info.display_name}_{channel_a}_{operation}_{constant}"
existing_fov_map = {f.display_name: f.id for f in store.get_fovs()}
if derived_name in existing_fov_map:
    derived_fov_id = existing_fov_map[derived_name]  # reuse
else:
    derived_fov_id = store.add_fov(...)  # create new
```

Same parameters produce same name, preventing FOV proliferation on re-runs.

### 5. Division by Zero Produces 0

```python
if operation == "divide":
    out = np.zeros_like(af)
    mask = bf != 0
    np.divide(af, bf, out=out, where=mask)  # zeros where divisor is 0
    return out
```

Using `np.divide` with `where` parameter avoids RuntimeWarning.

## Gotchas Discovered During Code Review

### 1. `channel_b` Falsy Check

```python
# Wrong — treats "" the same as None
if not channel_b:

# Correct — explicit identity check
if channel_b is None:
```

**Rule**: Always use `is None` for optional parameter checks, never truthiness.

### 2. CLI Menu Handler Gap

The generic plugin runner in `cli/menu.py` calls `registry.run_plugin()` with `parameters=None`. The image calculator requires parameters, so it crashes from the interactive menu. Custom handlers are needed (like `local_bg_subtraction` and `split_halo` have).

### 3. Memory Allocation for Bitwise Ops

`_apply_op` unconditionally creates float64 copies even for bitwise operations that only need int64. For large images (4096x4096), this wastes ~256 MB. Fix: separate bitwise path before float64 allocation.

### 4. Unchanged Channel Copy is Pure I/O Waste

Copying unchanged channels through numpy (read + decompress + allocate + compress + write) is the dominant cost. A zarr-level copy or `store.copy_image_channel()` would eliminate this.

## Prevention Rules for Future Plugins

| Rule | Why |
|------|-----|
| Use `is None` for optional param checks | Falsy values (0, "") are valid inputs |
| Validate array shapes before arithmetic | Prevents silent broadcasting or opaque numpy errors |
| Add a custom CLI menu handler | Generic runner doesn't collect parameters |
| Match dtype to operation semantics | Float64 for arithmetic, int for bitwise |
| Return test data from helpers, don't monkey-patch | `store._test_fov_id` fails type checkers |
| Use StrEnum for operation names | Catches typos at type-check time |

## Plugin Development Checklist

- [ ] Subclass `AnalysisPlugin`, implement `info()`, `validate()`, `run()`
- [ ] Separate pure computation from store I/O (core module)
- [ ] Define `get_parameter_schema()` with JSON Schema
- [ ] Use `is None` for all optional parameter checks
- [ ] Validate inputs at plugin boundary (channels exist, shapes match)
- [ ] Follow derived FOV pattern for non-destructive output
- [ ] Implement idempotent re-runs (check existing FOV by display_name)
- [ ] Add CLI menu handler in `_make_plugin_runner` dispatch
- [ ] Test core functions independently (unit tests)
- [ ] Test plugin integration with real ExperimentStore (integration tests)
- [ ] Use pytest fixtures with yield for store cleanup

## Related Documentation

- [Layer-Based Architecture](layer-based-architecture-redesign-learnings.md) — Global layer model, auto-measurement
- [Run-Scoped Architecture](run-scoped-architecture-refactor-learnings.md) — Plugin input requirements, derived FOV origins
- [Segment Module Encapsulation](segment-module-private-api-encapsulation-fix.md) — Hexagonal boundary enforcement
- [Zarr/SQLite State Mismatch](../database-issues/zarr-sqlite-state-mismatch-re-thresholding.md) — Write-Invalidate-Cleanup pattern
- [Core Module Security Fixes](../security-issues/core-module-p1-security-correctness-fixes.md) — Input validation patterns
