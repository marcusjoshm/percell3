---
title: "Finish Core Module: Address P2/P3 Review Findings"
type: refactor
date: 2026-02-12
---

# Finish Core Module: Address P2/P3 Review Findings

## Overview

The core module (percell3.core) implementation is functionally complete with all 4 phases delivered and all P1 critical issues resolved. 183 tests pass. This plan addresses the remaining 6 P2 and 5 P3 findings from the multi-agent code review to harden the module before downstream modules (02-07) build on it.

## Problem Statement

The remaining findings fall into three categories:

1. **API honesty** (P2-005, 006, 007, 010): Methods accept parameters they ignore or use opaque signatures that defeat type checking. Downstream modules will build on these APIs — fixing them now prevents API breaks later.

2. **Data safety** (P2-008): Zarr write functions don't validate array dimensions. A 3D array passed to a 2D writer silently corrupts data — dangerous in scientific imaging.

3. **Code quality** (P2-009, P3-011-015): Duplicated code, inconsistent style, missing introspection methods. These increase maintenance burden and reduce usability.

## Proposed Solution

Fix all P2 findings (required) and selected P3 findings (recommended). Group into three implementation phases to minimize test churn.

## Implementation Phases

### Phase A: API Cleanup (P2-005, 006, 007, 010)

All four fixes address the same theme: make the public API honest about what it accepts and does.

#### 1. Fix `get_cell_count` signature (P2-005)
**File:** `src/percell3/core/experiment_store.py:325-329`

Replace `**filters: object` with explicit keyword arguments matching `get_cells`:
```python
def get_cell_count(
    self,
    condition: Optional[str] = None,
    region: Optional[str] = None,
    is_valid: bool = True,
) -> int:
```

Also fix the redundant `cond_id` re-resolution on line 295 of `get_cells` while touching this area.

#### 2. Remove unused run ID parameters (P2-006)
**File:** `src/percell3/core/experiment_store.py`

Remove `segmentation_run_id` from `read_labels` and `threshold_run_id` from `read_mask`. These parameters are accepted but completely ignored — the zarr path doesn't incorporate them.

#### 3. Remove dead `**cell_filters` from `export_csv` (P2-007)
**File:** `src/percell3/core/experiment_store.py:471-481`

Remove `**cell_filters: object` from the signature. If filtering is needed later, add explicit parameters at that time.

#### 4. Fix silent region filter drop (P2-010)
**File:** `src/percell3/core/experiment_store.py:279-323`

Raise `ValueError` when `region` is provided without `condition`:
```python
if region is not None and condition is None:
    raise ValueError("'condition' is required when filtering by 'region'")
```

Also remove the redundant `cond_id_for_region` re-resolution (line 295).

**Tests for Phase A:**
- `test_get_cell_count_explicit_params` — verify condition/region/is_valid work
- `test_get_cells_region_without_condition_raises` — ValueError
- `test_export_csv_no_kwargs` — verify export still works without **kwargs
- Update existing tests that pass `segmentation_run_id` / `threshold_run_id`

---

### Phase B: Data Validation (P2-008)

#### 5. Add ndim validation to zarr write functions
**File:** `src/percell3/core/zarr_io.py`

Add at the top of `write_image_channel`, `write_labels`, and `write_mask`:
```python
if data.ndim != 2:
    raise ValueError(f"Expected 2D array (Y, X), got {data.ndim}D with shape {data.shape}")
```

**Tests for Phase B:**
- `test_write_image_rejects_3d` — ValueError for (1, H, W)
- `test_write_labels_rejects_3d` — ValueError for (H, W, 1)
- `test_write_mask_rejects_1d` — ValueError for (N,)
- Existing 2D tests continue passing

---

### Phase C: Code Quality (P2-009, P3-011-015)

#### 6. Extract duplicated row-mapping helpers (P2-009)
**File:** `src/percell3/core/queries.py`

Extract `_row_to_channel(row) -> ChannelConfig` and `_row_to_region(row) -> RegionInfo` helpers. Used by both `select_*` and `select_*_by_name` variants.

#### 7. Unify duplicated zarr path/metadata functions (P2-009)
**File:** `src/percell3/core/zarr_io.py`

- Collapse `image_group_path` and `label_group_path` into a shared implementation (they are character-for-character identical)
- Extract `_build_2d_multiscales(pixel_size_um)` shared by `_build_multiscales_label` and `_build_multiscales_mask`

#### 8. Expose `is_segmentation` on `add_channel` (P3-011)
**File:** `src/percell3/core/experiment_store.py`

Add `is_segmentation: bool = False` parameter, forward to `queries.insert_channel`.

#### 9. Standardize `Optional[X]` to `X | None` (P3-012)
**Files:** `models.py`, `queries.py`, `zarr_io.py`, `experiment_store.py`

All files already use `from __future__ import annotations`. Replace `Optional[X]` with `X | None` and remove `from typing import Optional` imports.

#### 10. Add `__repr__` to ExperimentStore (P3-013)
**File:** `src/percell3/core/experiment_store.py`

```python
def __repr__(self) -> str:
    return f"ExperimentStore({self._path!r})"
```

#### 11. Add introspection methods (P3-014)
**File:** `src/percell3/core/experiment_store.py` and `queries.py`

Add:
- `get_tags() -> list[str]`
- `get_segmentation_runs() -> list[dict]`
- `get_analysis_runs() -> list[dict]`

These are needed by the workflow engine (Module 6) to check preconditions.

#### 12. Make dataclasses frozen (P3-015)
**File:** `src/percell3/core/models.py`

Change all four dataclasses to `@dataclass(frozen=True)`. Verify no code mutates them.

**Tests for Phase C:**
- Existing tests pass (refactoring should not change behavior)
- `test_add_channel_is_segmentation` — verify flag works
- `test_get_tags` — round-trip create and list
- `test_get_segmentation_runs` — verify retrieval
- `test_frozen_dataclass` — verify immutability
- `test_experiment_store_repr` — verify string output

---

### Phase D: Housekeeping

#### 13. Update progress tracker
**File:** `docs/tracking/progress.md`

Mark Module 1 (Core) as complete.

#### 14. Update todo files
**Dir:** `todos/`

Rename resolved files from `pending` to `complete`.

## Acceptance Criteria

### Functional
- [x] `get_cell_count(condition="X")` works with explicit params, no `**kwargs`
- [x] `get_cells(region="r1")` without condition raises `ValueError`
- [x] `read_labels` / `read_mask` no longer accept unused run ID params
- [x] `export_csv` no longer accepts `**cell_filters`
- [x] 3D arrays rejected by all zarr write functions with clear error
- [x] `add_channel("DAPI", is_segmentation=True)` works
- [x] `get_tags()`, `get_segmentation_runs()`, `get_analysis_runs()` return data
- [x] All model dataclasses are frozen

### Quality
- [x] Zero duplicated row-mapping code in queries.py
- [x] `image_group_path` and `label_group_path` share implementation
- [x] All `Optional[X]` replaced with `X | None`
- [x] `ExperimentStore` has `__repr__`

### Testing
- [x] All existing 105 core tests pass
- [x] 21 new tests added (105 -> 126 core, 204 total)
- [x] Total test count: 204

## Dependencies & Risks

**Risk: Breaking existing test assertions.** The `read_labels`/`read_mask` signature changes and `export_csv` changes will break tests that pass the removed parameters. These tests need updating — search for `segmentation_run_id` and `threshold_run_id` in test files.

**Risk: Frozen dataclasses.** If any code mutates model instances, `frozen=True` will break it. Grep for attribute assignment on model instances before applying.

**Dependency:** No external dependencies. All changes are internal to `percell3.core`.

## Effort Estimate

- Phase A (API cleanup): ~30 min
- Phase B (ndim validation): ~10 min
- Phase C (code quality): ~45 min
- Phase D (housekeeping): ~5 min

## References

- `docs/solutions/security-issues/core-module-p1-security-correctness-fixes.md` — Prevention patterns from P1 fixes
- `todos/005-010` — P2 finding details
- `todos/011-015` — P3 finding details
- `docs/01-core/spec.md` — Module specification
- `docs/01-core/CLAUDE.md` — Module conventions
