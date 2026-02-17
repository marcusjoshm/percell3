---
title: Cellpose 4.0 API Breaking Changes - Class Rename + model_type Deprecation
date: 2026-02-16
updated: 2026-02-16
category: integration-issues
tags: [cellpose, third-party-api, runtime-error, dependency-version, segment, cpsam, sam]
modules: [segment]
severity: p1
symptoms:
  - "AttributeError: module 'cellpose.models' has no attribute 'Cellpose'"
  - 2 integration tests fail (test_synthetic_bright_disks, test_all_dark_image)
  - Runtime failure when CellposeAdapter instantiates model
  - 63 unit tests pass because they mock the segmenter
  - "model_type argument is not used in v4.0.1+. Ignoring this argument..."
  - All model selections silently resolve to cpsam regardless of model_name
root_cause: >
  Cellpose 4.0 introduced two breaking changes: (1) renamed models.Cellpose to
  models.CellposeModel, (2) deprecated model_type parameter entirely in favor of
  pretrained_model. The only built-in model is now 'cpsam' (Cellpose-SAM).
resolution_time: 30min (class rename fix); adapter migration pending
---

# Cellpose 4.0 API Breaking Change

## Problem

PerCell 3's `CellposeAdapter` fails at runtime with:

```
AttributeError: module 'cellpose.models' has no attribute 'Cellpose'
```

The error occurs in `src/percell3/segment/cellpose_adapter.py` line 45 when attempting to instantiate `models.Cellpose(model_type=..., gpu=...)`.

Two integration tests (`@pytest.mark.slow`) fail. All 63 unit tests pass because they mock the segmenter via the `BaseSegmenter` ABC.

## Investigation

1. **Version check**: `pip show cellpose` confirmed version **4.0.8** installed.
2. **API inspection**: `python -c "from cellpose import models; print(dir(models))"` showed `CellposeModel` present but `Cellpose` absent.
3. **Changelog review**: Cellpose 4.0 renamed the main model class as part of an API cleanup.

## Root Cause

The code was written against the Cellpose 3.x API. Cellpose 4.0 introduced a backward-incompatible rename:

| Cellpose 3.x | Cellpose 4.0+ |
|---|---|
| `models.Cellpose` | `models.CellposeModel` |

The `pyproject.toml` specifies `cellpose>=3.0` with no upper bound, so `pip install` pulls the latest (4.0.8).

## Solution

Use a `getattr()` fallback pattern for version-compatible instantiation:

```python
# At module level in cellpose_adapter.py, inside the lazy import block
from cellpose import models

_CellposeModel = getattr(models, "CellposeModel", None) or getattr(models, "Cellpose")

# Then in _get_model():
self._model_cache[key] = _CellposeModel(
    model_type=model_name,
    gpu=gpu,
)
```

**How it works:**
1. Tries `CellposeModel` first (4.x API)
2. Falls back to `Cellpose` (3.x API) if not found
3. Raises `AttributeError` if neither exists (unsupported version)
4. No version string parsing required

## Prevention Strategies

### 1. Version-Compatible Adapter Pattern

For any external scientific library adapter, use defensive imports:

```python
def _get_model_class():
    from cellpose import models
    return getattr(models, "CellposeModel", None) or getattr(models, "Cellpose")
```

Apply this to all adapters behind the hexagonal architecture boundary.

### 2. Adapter Smoke Tests

Add lightweight tests that instantiate the real adapter (not mocked) without requiring test data:

```python
def test_cellpose_adapter_instantiates():
    pytest.importorskip("cellpose")
    from percell3.segment import CellposeAdapter
    adapter = CellposeAdapter()
    assert hasattr(adapter, "segment")

def test_cellpose_version_supported():
    cellpose = pytest.importorskip("cellpose")
    major = int(cellpose.__version__.split(".")[0])
    assert major in [3, 4], f"Cellpose {cellpose.__version__} not tested"
```

### 3. Dependency Version Bounds

Consider adding an upper bound in `pyproject.toml` for stability:

```toml
"cellpose>=3.0,<5.0"
```

### 4. CI Integration Tests

Run `@pytest.mark.slow` integration tests in CI (at least nightly) with a version matrix:

```yaml
strategy:
  matrix:
    cellpose-version: ["3.0", "4.0"]
```

### 5. General Pattern for Scientific Python Libraries

Scientific libraries break APIs frequently between major versions. Design for resilience:
- Pin major version bounds in `pyproject.toml`
- Use `hasattr()` checks in adapters
- Document tested versions in adapter docstrings
- Tag fragile code with `# COMPAT: depends on cellpose.models API`

## Additional Context: Segment Module Review

This issue was discovered during a comprehensive code review of the `feat/segment-module` branch (commit `c2514d8`). The review identified 9 total findings:

| ID | Priority | Finding |
|---|---|---|
| 016 | P1 | Cellpose 4.0 API break (this document) |
| 017 | P1 | Private `store._conn` access in 3 places |
| 018 | P1 | `np.load(allow_pickle=True)` security warning |
| 019 | P2 | Engine `run()` doesn't expose all params |
| 020 | P2 | Duplicated logic in `roi_import.py` |
| 021 | P2 | Mutable `list` in frozen dataclass |
| 022 | P2 | Row-by-row cell INSERT performance |
| 023 | P3 | `segment_batch()` dead code (YAGNI) |
| 024 | P3 | Stateless classes could be functions |

See `todos/016-024` for full details on each finding.

## Cellpose 4.x: `model_type` Deprecated — `pretrained_model` API (2026-02-16)

### Discovery

During a review of the full adapter pipeline with Cellpose 4.0.8, a second breaking change was identified: the `model_type` parameter passed to `CellposeModel()` is **completely ignored** with a deprecation warning.

```python
# cellpose/models.py (v4.0.8), line 108-111
if model_type is not None:
    models_logger.warning(
        "model_type argument is not used in v4.0.1+. Ignoring this argument..."
    )
```

### Impact

| What happens | Detail |
|---|---|
| `model_type="cyto3"` | Ignored. cpsam loads instead. |
| `model_type="nuclei"` | Ignored. cpsam loads instead. |
| `pretrained_model` default | `"cpsam"` (Cellpose-SAM, ViT backbone) |
| `MODEL_NAMES` in 4.x | `['cpsam']` — the only built-in model |
| Old model names | Fall back to cpsam with a warning log |

### The `cpsam` Model (Cellpose-SAM)

Cellpose 4.x ships a single built-in model: **cpsam** (Cellpose-SAM), available since v4.0.4. It uses a Vision Transformer (ViT) backbone adapted from the SAM (Segment Anything Model) foundation model. This replaces all previous specialized models (cyto3, nuclei, etc.) with a single general-purpose model.

### Current Adapter Status

The adapter uses `model_type=model_name` which is silently ignored. The `KNOWN_CELLPOSE_MODELS` allowlist does **not** include `cpsam`, meaning the only working 4.x model is blocked by the allowlist. In practice, segmentation works because old names like `cyto3` pass the allowlist and Cellpose silently falls back to cpsam.

**Pending fix:** See [todo-054](../../../todos/054-pending-p1-cellpose4-model-type-deprecated.md) for the migration plan.

### Security: `weights_only=True` in 4.x

Cellpose 4.x model loading uses `torch.load(filename, weights_only=True)` (confirmed in `cellpose/vit_sam.py` lines 159-163). This mitigates the pickle-based arbitrary code execution risk that was the concern in todo-045. The `KNOWN_CELLPOSE_MODELS` allowlist remains valuable as defense-in-depth, especially for any Cellpose 3.x installations where `weights_only` is not used.

## User Testing Confirmation (2026-02-16)

Segmentation was tested via the interactive menu (`percell3` → option 3: Segment cells) and confirmed **working as expected**. The segmentation pipeline successfully:
- Reads images from ExperimentStore
- Runs Cellpose (functionally using cpsam model)
- Writes label images to labels.zarr
- Extracts cell properties to the cells table
- Reports results with cell count and timing

Note: Although the user selected `cyto3` in the menu, Cellpose 4.x silently ran `cpsam`. The results are correct — the model name metadata in the database is what's inaccurate.

## Cross-References

- [Todo 033: Cellpose 4.0 API Break (class rename — COMPLETE)](../../../todos/033-complete-p1-cellpose4-api-break.md)
- [Todo 054: Cellpose 4.x model_type deprecated (PENDING)](../../../todos/054-pending-p1-cellpose4-model-type-deprecated.md)
- [Todo 055: Stale model names in CLI/menu (PENDING)](../../../todos/055-pending-p2-stale-model-names-cli-menu.md)
- [Module 3 Specification](../../03-segment/spec.md)
- [Headless Segmentation Engine Plan](../../plans/2026-02-13-feat-segmentation-engine-headless-plan.md)
- [Core Module Security Fixes](../security-issues/core-module-p1-security-correctness-fixes.md) -- related input validation patterns
- [IO Module Logic Error Fixes](../logic-errors/io-module-p1-z-projection-and-input-validation-fixes.md) -- related float64/memory patterns
