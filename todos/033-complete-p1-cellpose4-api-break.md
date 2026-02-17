---
status: complete
priority: p1
issue_id: "033"
tags: [code-review, segment, cellpose, compatibility]
dependencies: []
---

# Cellpose 4.0 API Break — `models.Cellpose` Renamed to `models.CellposeModel`

## Problem Statement

`CellposeAdapter._get_model()` uses `models.Cellpose(...)` which was renamed to `models.CellposeModel` in Cellpose 4.0. With the installed version (4.0.8), this causes `AttributeError: module 'cellpose.models' has no attribute 'Cellpose'` at runtime. This is a **hard crash** — segmentation cannot run at all.

2 integration tests fail: `test_synthetic_bright_disks` and `test_all_dark_image`.

## Findings

- **File:** `src/percell3/segment/cellpose_adapter.py:45`
- **Error:** `AttributeError: module 'cellpose.models' has no attribute 'Cellpose'`
- Cellpose 4.0.8 available classes: `CellposeModel`, `Transformer` (no `Cellpose`)
- The docstring on `_get_model` (line 32) also references the old class name

## Proposed Solutions

### Option 1 (Recommended): Support both Cellpose 3.x and 4.x

```python
model_cls = getattr(models, "CellposeModel", None) or getattr(models, "Cellpose")
self._model_cache[key] = model_cls(model_type=model_name, gpu=gpu)
```

- Pros: Works with both old and new Cellpose versions
- Cons: Slightly more complex
- Effort: Small
- Risk: Low

### Option 2: Target Cellpose 4.x only

```python
self._model_cache[key] = models.CellposeModel(model_type=model_name, gpu=gpu)
```

- Pros: Simplest fix
- Cons: Breaks for users on Cellpose 3.x
- Effort: Small
- Risk: Low (if we pin cellpose>=4.0 in pyproject.toml)

## Technical Details

- Affected files: `src/percell3/segment/cellpose_adapter.py` (lines 45, 32)
- Update docstring to be version-agnostic

## Acceptance Criteria

- [x] `CellposeAdapter` works with installed Cellpose 4.0.8
- [x] Both integration tests pass (`test_synthetic_bright_disks`, `test_all_dark_image`)
- [x] All 65 segment tests pass (63 unit + 2 integration)

## Work Log

### 2026-02-16 — Code Review Discovery
Identified during segment module code review. Cellpose 4.0 renamed `models.Cellpose` to `models.CellposeModel`. Runtime crash confirmed.

### 2026-02-16 — Fixed
Applied Option 1 (support both 3.x and 4.x) using `getattr()` fallback. Also fixed `model.eval()` return value unpacking — Cellpose 4.x returns 3 values instead of 4. Used `results[0]` indexing for version-compatible unpacking. All 65 segment tests pass including both integration tests.
