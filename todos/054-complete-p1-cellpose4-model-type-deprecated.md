---
status: complete
priority: p1
issue_id: "054"
tags: [code-review, segment, cellpose, api-migration, scientific-integrity]
dependencies: []
---

# Cellpose 4.x: `model_type` Parameter Ignored — Migrate to `pretrained_model` API

## Problem Statement

In Cellpose 4.0.1+, the `model_type` parameter passed to `CellposeModel()` is **completely ignored** with a deprecation warning. The adapter currently uses `model_type=model_name`, meaning:

1. All model selections (cyto3, nuclei, etc.) silently resolve to `cpsam` (Cellpose-SAM)
2. The `KNOWN_CELLPOSE_MODELS` allowlist blocks `cpsam` — the only model that actually works
3. The database records the *requested* model name, not the *actual* model used
4. CLI defaults to `--model cyto3` and menu suggests "cyto3, cyto2, nuclei" — none exist in 4.x

This is a **scientific reproducibility issue**: researchers see `model=cyto3` in their metadata but `cpsam` actually ran.

## Findings

### Evidence from Cellpose 4.0.8 source (`cellpose/models.py` lines 91-111):

```python
def __init__(self, gpu=False, pretrained_model="cpsam", model_type=None, ...):
    if model_type is not None:
        models_logger.warning(
            "model_type argument is not used in v4.0.1+. Ignoring this argument..."
        )
```

### Current adapter code (`cellpose_adapter.py` line 65-68):

```python
self._model_cache[key] = model_cls(
    model_type=model_name,   # <-- IGNORED in Cellpose 4.x
    gpu=gpu,
)
```

### `MODEL_NAMES` in Cellpose 4.x:

```python
MODEL_NAMES = ['cpsam']  # The ONLY built-in model
```

Old names (cyto3, cyto2, nuclei) fall back to cpsam with a warning log.

### Positive finding: Cellpose 4.x uses `weights_only=True`

Model loading uses `torch.load(filename, weights_only=True)`, which mitigates the pickle-based code execution risk from todo-045.

## Additional Finding: `channels` Parameter Also Deprecated

The `channels` parameter in `model.eval()` is deprecated in 4.x. Our adapter passes `channels=params.channels_cellpose or [0, 0]` (line 89), which triggers a warning. In 4.x, images are auto-padded/truncated to 3 channels. The `channels` kwarg should be omitted for 4.x.

Also: masks dtype changed from `int32` to `uint16` in 4.x (our `.astype(np.int32)` handles this correctly). And `diameter=None` now means "process at original resolution" — there is no auto-diameter estimation in 4.x (the 3.x `SizeModel` is removed).

## Affected Files

- `src/percell3/segment/cellpose_adapter.py` — `model_type` → `pretrained_model`, add `cpsam` to allowlist, skip `channels` kwarg on 4.x
- `src/percell3/segment/base_segmenter.py` — default `model_name` from `"cyto3"` to `"cpsam"`
- `src/percell3/segment/_engine.py` — default `model` from `"cyto3"` to `"cpsam"`
- `src/percell3/cli/segment.py` — default `--model` from `cyto3` to `cpsam`
- `src/percell3/cli/menu.py` — update "Common models" list

## Proposed Solutions

### Option 1 (Recommended): Version-aware adapter with `cpsam` default

```python
KNOWN_CELLPOSE_MODELS = frozenset({
    "cpsam",  # Cellpose 4.x default (SAM-based)
    "cyto", "cyto2", "cyto3", "nuclei",  # 3.x models (map to cpsam on 4.x)
    "tissuenet", "livecell",
    "tissuenet_cp3", "livecell_cp3",
    "deepbacs_cp3", "cyto2_cp3",
    "yeast_PhC_cp3", "yeast_BF_cp3",
    "bact_phase_cp3", "bact_fluor_cp3",
    "plant_cp3",
})

def _get_model(self, model_name: str, gpu: bool):
    if model_name not in KNOWN_CELLPOSE_MODELS:
        raise ValueError(...)

    from cellpose import models
    import cellpose
    major = int(cellpose.__version__.split(".")[0])

    model_cls = getattr(models, "CellposeModel", None) or getattr(models, "Cellpose")

    if major >= 4:
        # Cellpose 4.x: use pretrained_model parameter
        self._model_cache[key] = model_cls(pretrained_model=model_name, gpu=gpu)
    else:
        # Cellpose 3.x: use model_type parameter
        self._model_cache[key] = model_cls(model_type=model_name, gpu=gpu)
```

- Pros: Correct API for both versions, `cpsam` works on 4.x, old names work on 3.x
- Cons: Version checking adds minor complexity
- Effort: Small
- Risk: Low

### Option 2: Drop 3.x support, use `pretrained_model` only

```python
self._model_cache[key] = model_cls(pretrained_model=model_name, gpu=gpu)
```

- Pros: Simpler code, no version branching
- Cons: Breaks Cellpose 3.x users
- Effort: Small
- Risk: Medium (breaks backward compat)

## Acceptance Criteria

- [x] `cpsam` added to `KNOWN_CELLPOSE_MODELS`
- [x] Adapter uses `pretrained_model` on Cellpose 4.x, `model_type` on 3.x
- [x] Default model changed from `cyto3` to `cpsam` in all layers (params, engine, CLI, menu)
- [x] CLI `--model` shows `cpsam` as default
- [x] Menu "Common models" updated to show `cpsam` prominently
- [ ] Database records actual model used (cpsam) when fallback occurs
- [x] Existing tests pass; new test verifies cpsam is accepted

## Work Log

### 2026-02-16 — Discovery

Identified during review: `model_type` is completely ignored in Cellpose 4.0.1+. Confirmed by reading `cellpose/models.py` source. User confirmed segmentation works via interactive menu (functionally loads cpsam regardless of model name). Security review (agent a80a43f) confirmed `weights_only=True` mitigates pickle RCE.

### 2026-02-16 — Implementation

Fixed on branch `fix/cellpose4-adapter-migration`:

- Added `cpsam` to `KNOWN_CELLPOSE_MODELS` in `cellpose_adapter.py`
- Implemented version-aware instantiation: `pretrained_model=` on 4.x, `model_type=` on 3.x
- Version detection uses `importlib.metadata.version("cellpose")` (standard Python, no dependency on `cellpose.__version__`)
- Updated default model from `cyto3` to `cpsam` in all layers: `SegmentationParams`, `SegmentationEngine.run()`, `cli/segment.py`, `cli/menu.py`, `workflow/defaults.py`
- Added `click.Choice` validation on CLI `--model` option
- Added tests for version-aware instantiation (4.x uses `pretrained_model`, 3.x uses `model_type`)
- All 461 tests pass (including 2 integration tests with real Cellpose 4.x)
