---
title: "feat: Headless Segmentation Engine with Cellpose (Module 3a)"
type: feat
date: 2026-02-13
module: segment
supersedes: 2026-02-13-feat-segmentation-module-cellpose-plan.md
brainstorm: docs/brainstorms/2026-02-13-cellpose-segmentation-workflow-brainstorm.md
---

# Headless Segmentation Engine with Cellpose (Module 3a)

## Overview

Build the headless segmentation engine for PerCell 3, wrapping Cellpose behind an
abstract interface. The module reads images from ExperimentStore, runs cell
segmentation via the Cellpose Python API, stores integer label images in
`labels.zarr`, and populates the `cells` table in SQLite with extracted cell
properties (centroid, bounding box, area, perimeter, circularity).

This is **Module 3a** — the domain logic and CLI only. No napari, no GUI. The
napari viewer and cellpose-napari plugin integration are deferred to Module 3b
(see brainstorm for rationale).

## Problem Statement / Motivation

PerCell 3 currently imports TIFF images into experiments (Module 2: IO) but cannot
segment cells. Users need to:

1. Run Cellpose on any channel (DAPI, GFP, etc.) to detect cell boundaries
2. Store label images alongside raw images in the same experiment
3. Extract quantitative cell properties for downstream analysis
4. Import pre-existing segmentations (from Cellpose GUI `_seg.npy` files or TIFFs)

### Design Decisions (from brainstorm)

- **No more ImageJ ROIs**: PerCell 2 saved Cellpose output as ImageJ ROI lists.
  PerCell 3 stores labels natively as int32 zarr arrays. ROI rasterization is an
  unnecessary detour.
- **Automated path uses direct API**: `model.eval()` returns numpy masks in memory.
  No intermediate files.
- **GUI deferred to Module 3b**: napari with cellpose-napari plugin is the primary
  GUI. Native Cellpose GUI supported as fallback via `_seg.npy` import. Both require
  the headless engine as foundation.
- **Output: zarr + SQLite only**: No auto-export of TIFFs or CSVs. Export on demand
  via `percell3 export`.

## Dependencies & Prerequisites

- **Module 1 (Core)**: Complete. ExperimentStore provides `read_image_numpy()`,
  `write_labels()`, `add_cells()`, `add_segmentation_run()`.
- **cellpose>=3.0**: Already in `pyproject.toml`
- **scikit-image>=0.21**: Already in `pyproject.toml` (for `regionprops`)
- **scipy>=1.10**: Already in `pyproject.toml`
- **Workflow contract**: `percell3.segment.SegmentationEngine` with
  `.run(store, channel=, model=, diameter=)` method
  (from `workflow/defaults.py:140-143`)

No dependency on IO, CLI, or Workflow modules in domain code.

## Technical Approach

### Architecture

```
                BaseSegmenter (ABC)
                     |
              CellposeAdapter
                     |
        SegmentationEngine.run()
           /         |         \
   read_image    segment()   write_labels
   (Store)      (Cellpose)    (Store)
                     |
             LabelProcessor
           extract_cells() -> CellRecords
                     |
              add_cells(Store)
```

### File Structure

```
src/percell3/segment/
├── __init__.py              # Public API: SegmentationEngine, SegmentationParams, etc.
├── base_segmenter.py        # ABC interface + SegmentationParams dataclass
├── cellpose_adapter.py      # Cellpose wrapper with model caching
├── label_processor.py       # Label image -> CellRecord extraction
└── roi_import.py            # Import pre-existing labels (_seg.npy, TIFF)

tests/test_segment/
├── __init__.py
├── conftest.py              # Shared fixtures (synthetic images, mock segmenter)
├── test_base_segmenter.py   # Interface contract tests
├── test_cellpose_adapter.py # Cellpose integration (marked @pytest.mark.slow)
├── test_label_processor.py  # Property extraction tests
├── test_roi_import.py       # ROI import tests
└── test_engine.py           # End-to-end pipeline tests
```

## Implementation Phases

### Phase 1: Foundation — SegmentationParams + BaseSegmenter

**Files**: `base_segmenter.py`, `__init__.py`

- [ ] Create `SegmentationParams` frozen dataclass:
  ```python
  # base_segmenter.py
  @dataclass(frozen=True)
  class SegmentationParams:
      channel: str
      model_name: str = "cyto3"
      diameter: float | None = None
      flow_threshold: float = 0.4
      cellprob_threshold: float = 0.0
      gpu: bool = True
      min_size: int = 15
      normalize: bool = True
      channels_cellpose: list[int] | None = None
  ```
- [ ] Add `__post_init__` validation:
  - `model_name` not empty
  - `min_size >= 0`
  - `0 <= flow_threshold <= 3`
  - `channel` not empty
- [ ] Create `BaseSegmenter` ABC with:
  - `segment(image: np.ndarray, params: SegmentationParams) -> np.ndarray`
  - `segment_batch(images: list[np.ndarray], params: SegmentationParams) -> list[np.ndarray]`
- [ ] Create `SegmentationResult` frozen dataclass:
  ```python
  # base_segmenter.py
  @dataclass(frozen=True)
  class SegmentationResult:
      run_id: int
      cell_count: int
      regions_processed: int
      warnings: list[str] = field(default_factory=list)
      elapsed_seconds: float = 0.0
  ```
- [ ] Export from `__init__.py`: `SegmentationParams`, `SegmentationResult`,
  `BaseSegmenter`, `SegmentationEngine` (added in Phase 4)

**Tests** (`test_base_segmenter.py`):
- [ ] `SegmentationParams` defaults are correct
- [ ] Validation rejects empty `model_name`
- [ ] Validation rejects `min_size < 0`
- [ ] Validation rejects `flow_threshold` outside [0, 3]
- [ ] Validation rejects empty `channel`
- [ ] Cannot instantiate `BaseSegmenter` directly (ABC)
- [ ] Concrete subclass with `segment()`/`segment_batch()` can be instantiated

---

### Phase 2: LabelProcessor — Cell Property Extraction

**File**: `label_processor.py`

- [ ] Create `LabelProcessor` class with `extract_cells()` method:
  ```python
  # label_processor.py
  class LabelProcessor:
      def extract_cells(
          self,
          labels: np.ndarray,
          region_id: int,
          segmentation_id: int,
          pixel_size_um: float | None = None,
      ) -> list[CellRecord]:
  ```
- [ ] Use `skimage.measure.regionprops(labels)` to extract:
  - `label_value` from `prop.label`
  - `centroid_x`, `centroid_y` from `prop.centroid`
    (**CRITICAL**: regionprops returns `(row, col)` = `(y, x)`, must swap)
  - `bbox_x, bbox_y, bbox_w, bbox_h` from `prop.bbox`
    (`min_row, min_col, max_row, max_col` -> `x=min_col, y=min_row, w=max_col-min_col, h=max_row-min_row`)
  - `area_pixels` from `prop.area` (use `float()` to avoid integer dtype issues)
  - `area_um2 = float(area_pixels) * pixel_size_um**2` (if pixel_size provided, use `float64`)
  - `perimeter` from `prop.perimeter`
  - `circularity = 4.0 * math.pi * area / perimeter**2`
    (**GUARD**: if `perimeter == 0`, `circularity = 0.0`)
- [ ] Return `list[CellRecord]` (import from `percell3.core.models`)
- [ ] Handle empty label image (no cells) -> return empty list
- [ ] Use `float64` for all arithmetic (institutional learning: integer overflow)

**Tests** (`test_label_processor.py`):
- [ ] Known 30x30 square: area=900, bbox correct, centroid at (65, 65) for labels[50:80, 50:80]
- [ ] Two objects: returns 2 CellRecords with correct label_values (1, 2)
- [ ] Centroid coordinate swap: verify x=col, y=row (not reversed)
- [ ] With pixel_size_um=0.65: area_um2 = area_pixels * 0.65^2
- [ ] Without pixel_size_um: area_um2 is None
- [ ] Empty label image (all zeros): returns empty list
- [ ] Circularity of circle approx 1.0 (within tolerance, use `skimage.draw.disk`)
- [ ] Zero-perimeter guard: single-pixel cell, circularity = 0.0

---

### Phase 3: CellposeAdapter

**File**: `cellpose_adapter.py`

- [x] Create `CellposeAdapter(BaseSegmenter)`:
  ```python
  # cellpose_adapter.py
  class CellposeAdapter(BaseSegmenter):
      def __init__(self) -> None:
          self._model_cache: dict[tuple[str, bool], Any] = {}

      def _get_model(self, model_name: str, gpu: bool) -> Any:
          key = (model_name, gpu)
          if key not in self._model_cache:
              from cellpose import models  # Lazy import
              self._model_cache[key] = models.Cellpose(
                  model_type=model_name, gpu=gpu,
              )
          return self._model_cache[key]

      def segment(self, image: np.ndarray, params: SegmentationParams) -> np.ndarray:
          model = self._get_model(params.model_name, params.gpu)
          masks, flows, styles, diams = model.eval(
              image,
              diameter=params.diameter,
              flow_threshold=params.flow_threshold,
              cellprob_threshold=params.cellprob_threshold,
              min_size=params.min_size,
              normalize=params.normalize,
              channels=params.channels_cellpose or [0, 0],
          )
          return masks.astype(np.int32)

      def segment_batch(self, images: list[np.ndarray],
                        params: SegmentationParams) -> list[np.ndarray]:
          model = self._get_model(params.model_name, params.gpu)
          results = model.eval(
              images,
              diameter=params.diameter,
              flow_threshold=params.flow_threshold,
              cellprob_threshold=params.cellprob_threshold,
              min_size=params.min_size,
              normalize=params.normalize,
              channels=params.channels_cellpose or [0, 0],
          )
          # model.eval with list returns (list[masks], list[flows], list[styles], list[diams])
          masks_list = results[0]
          return [m.astype(np.int32) for m in masks_list]
  ```
- [x] Lazy `from cellpose import models` ONLY in `_get_model()` (not at module level)
- [x] Handle Cellpose returning 0 cells: masks will be all-zero, which is correct
- [x] Model caching by `(model_name, gpu)` tuple to avoid redundant model loading

**Tests** (`test_cellpose_adapter.py`):
- [x] Synthetic image with 2 bright disks: detects >= 2 cells (mark `@pytest.mark.slow`)
- [x] Output dtype is `np.int32`
- [x] Output shape matches input shape
- [x] Model caching: second call with same params reuses cached model
- [x] All-dark image: returns all-zero labels (0 cells)

---

### Phase 4: SegmentationEngine — Pipeline Orchestration

**File**: `__init__.py` (add `SegmentationEngine` class)

- [x] Create `SegmentationEngine`:
  ```python
  # __init__.py
  class SegmentationEngine:
      def __init__(self, segmenter: BaseSegmenter | None = None) -> None:
          self._segmenter = segmenter

      def run(
          self,
          store: ExperimentStore,
          channel: str = "DAPI",
          model: str = "cyto3",
          diameter: int | float | None = None,
          regions: list[str] | None = None,
          condition: str | None = None,
          progress_callback: Callable[[int, int, str], None] | None = None,
      ) -> SegmentationResult:
  ```
- [x] Pipeline steps:
  1. Validate channel exists in store (`store.get_channel(channel)` — raises `ChannelNotFoundError`)
  2. Create `SegmentationParams` from kwargs
  3. Instantiate `CellposeAdapter` if no segmenter provided (lazy default)
  4. Get regions: `store.get_regions(condition=condition)`, filter by `regions` list if provided
  5. Validate regions list is non-empty (raise `ValueError` if no regions match)
  6. Call `store.add_segmentation_run(channel, model, params_dict)` -> `run_id`
  7. For each region (one at a time — memory streaming):
     - `image = store.read_image_numpy(region.name, region.condition, channel)`
     - `labels = segmenter.segment(image, params)`
     - `store.write_labels(region.name, region.condition, labels, run_id)`
     - `cells = LabelProcessor().extract_cells(labels, region.id, run_id, region.pixel_size_um)`
     - `store.add_cells(cells)`
     - Accumulate `total_cells += len(cells)`
     - Collect warnings if `len(cells) == 0`
     - Call `progress_callback(i+1, total, region.name)` if provided
  8. Update cell count: `queries.update_segmentation_run_cell_count(store._conn, run_id, total_cells)`
  9. Return `SegmentationResult(run_id, total_cells, len(regions), warnings, elapsed)`
- [x] Handle no-cells case: log warning per region, still write empty labels
- [x] Handle missing channel: raise `ChannelNotFoundError` before any processing
- [x] Use `time.monotonic()` for elapsed time (matching ImportEngine pattern)
- [x] **Transaction strategy**: Per-region commit. Each region's labels + cells are committed
  independently. If region N fails, regions 1..N-1 are preserved. Failed region is
  logged as warning in `SegmentationResult.warnings`, segmentation continues.
- [x] **Parameters JSON**: Store all `SegmentationParams` fields in `segmentation_runs.parameters`
  as JSON dict: `{"diameter": 60, "flow_threshold": 0.4, "gpu": true, ...}`.
  Enables reproducibility.

**Tests** (`test_engine.py`):
- [x] End-to-end with mock segmenter: labels stored in zarr, cells in SQLite
- [x] Progress callback called once per region with correct (current, total, name)
- [x] Missing channel raises `ChannelNotFoundError`
- [x] Region filtering by name: only specified regions processed
- [x] Condition filtering: only regions with matching condition processed
- [x] Empty segmentation (0 cells): warning in result, labels stored as zeros
- [x] Re-segmentation: new run_id, old cells preserved, both queryable
- [x] SegmentationResult.cell_count matches actual cells in DB
- [x] Multiple regions: cells have correct region_ids

---

### Phase 5: RoiImporter — Pre-Existing Labels

**File**: `roi_import.py`

- [x] Create `RoiImporter`:
  ```python
  # roi_import.py
  class RoiImporter:
      def import_labels(
          self,
          labels: np.ndarray,
          store: ExperimentStore,
          region: str,
          condition: str,
          channel: str = "manual",
          source: str = "manual",
          timepoint: str | None = None,
      ) -> int:
          """Import a pre-computed label image. Returns segmentation run ID."""

      def import_cellpose_seg(
          self,
          seg_path: Path,
          store: ExperimentStore,
          region: str,
          condition: str,
          channel: str = "manual",
          timepoint: str | None = None,
      ) -> int:
          """Import a Cellpose _seg.npy file. Returns segmentation run ID."""
  ```
- [x] `import_labels()` steps:
  1. Validate labels dtype (must be integer — raise `ValueError` for float)
  2. Validate labels is 2D (raise `ValueError` for 3D)
  3. Cast to `int32` if needed
  4. Create segmentation run with `model_name=source`
  5. Write labels to store
  6. Extract cells via `LabelProcessor`
  7. Insert cells
  8. Return `run_id`
- [x] `import_cellpose_seg()` steps:
  1. Load `_seg.npy` with `np.load(path, allow_pickle=True).item()`
  2. Extract `masks` array from the dict
  3. Extract `diameter` and other params if present (store in segmentation run parameters)
  4. Delegate to `import_labels()` with `source="cellpose-gui"`
- [x] Validate `_seg.npy` structure: must be dict with `"masks"` key

**Tests** (`test_roi_import.py`):
- [x] Import 2-cell label image: cells in DB match
- [x] Labels round-trip: stored labels match input
- [x] Non-integer labels dtype raises ValueError
- [x] Zero-cell label image: run created, 0 cells
- [x] Import `_seg.npy` file: masks extracted, cells in DB
- [x] `_seg.npy` parameters captured in segmentation run
- [x] Invalid `_seg.npy` (no "masks" key) raises ValueError

---

### Phase 6: CLI Integration

**Files**: `src/percell3/cli/segment_cmd.py`, `main.py`, `menu.py`

- [ ] Create `src/percell3/cli/segment_cmd.py`:
  ```python
  # segment_cmd.py
  @click.command("segment")
  @click.option("-e", "--experiment", required=True, type=click.Path(exists=True))
  @click.option("-c", "--channel", default="DAPI")
  @click.option("--model", default="cyto3", type=click.Choice(["cyto3", "nuclei", "cyto2"]))
  @click.option("--diameter", default=None, type=float)
  @click.option("--condition", default=None)
  @click.option("--regions", multiple=True)
  @click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
  ```
- [ ] Add `import-labels` subcommand for importing pre-existing labels:
  ```python
  @click.command("import-labels")
  @click.option("-e", "--experiment", required=True, type=click.Path(exists=True))
  @click.option("--labels", required=True, type=click.Path(exists=True),
                help="Path to label image (TIFF) or Cellpose _seg.npy file.")
  @click.option("--region", required=True)
  @click.option("--condition", required=True)
  @click.option("--channel", default="manual")
  @click.option("--source", default="manual")
  ```
- [ ] Replace stub import in `main.py`: `from percell3.cli.segment_cmd import segment`
- [ ] Add menu item handler in `menu.py` (option 3: "Segment cells")
- [ ] Progress bar via `make_progress()` helper
- [ ] `@error_handler` decorator for consistent exit codes
- [ ] Shared `_run_segmentation()` function for CLI/menu parity

**Tests** (`tests/test_cli/test_segment.py`):
- [ ] `percell3 segment -e exp --channel DAPI --yes` with mock segmenter
- [ ] `percell3 import-labels -e exp --labels mask.tif --region r1 --condition ctrl`
- [ ] Help text shows all options
- [ ] Missing experiment raises error
- [ ] Every `@click.option` has a corresponding CliRunner test

---

## Dependency Graph

```
Phase 1 (Params + ABC)  ───┐
Phase 2 (LabelProcessor) ──├──▶ Phase 4 (Engine) ──▶ Phase 6 (CLI)
Phase 3 (CellposeAdapter) ─┘         |
                                      └──▶ Phase 5 (ROI Import)
```

Phases 1-3 are independent (can be built in parallel). Phase 4 depends on all three.
Phases 5-6 depend on Phase 4.

## Institutional Learnings to Apply

From `docs/solutions/`:

1. **Integer overflow** (`docs/solutions/logic-errors/io-module-p1-z-projection-and-input-validation-fixes.md`):
   Use `dtype=np.float64` when computing `area_um2`, `circularity`, and any
   accumulation operations. Never rely on input dtype for arithmetic.

2. **Memory streaming** (same source):
   Process regions one at a time. Never load all region images into a list.

3. **Explicit error on unknown values** (same source):
   Validate `model_name` against known models. Raise `ValueError` for unknowns —
   no silent fallbacks.

4. **Input validation at boundaries** (`docs/solutions/security-issues/core-module-p1-security-correctness-fixes.md`):
   Channel names validated by ExperimentStore. Params validated in
   `SegmentationParams.__post_init__`. Validate name patterns for model names.

5. **Adapter pattern / lazy imports** (`docs/solutions/architecture-decisions/cli-module-code-review-findings.md`):
   Cellpose import is lazy (inside `_get_model()`). Domain code
   (`SegmentationEngine`) never imports Cellpose directly — always through
   `BaseSegmenter` interface. `time percell3 --help` must stay under 500ms.

6. **Exception hierarchy discipline** (`docs/solutions/security-issues/core-module-p1-security-correctness-fixes.md`):
   One exception per domain concept. Reuse `ChannelNotFoundError` from core.
   Don't create new exceptions unless needed.

7. **Transaction safety** (same source):
   `insert_cells()` in queries.py already wraps batch inserts in try/rollback.
   If adding new batch operations, follow the same pattern.

8. **Dual-mode CLI** (`docs/solutions/integration-issues/cli-io-dual-mode-review-fixes.md`):
   Menu handlers and Click commands must share logic via a common function.
   Every `@click.option` must have a CliRunner test.

## Edge Cases

| Scenario | Handling |
|----------|----------|
| Image with 0 cells detected | Store all-zero labels, log warning, cell_count=0 |
| Very large image (>4096px) | Process as single image (Cellpose handles tiling internally) |
| Re-segmentation of same region | New `segmentation_run`, old cells preserved |
| Channel doesn't exist | Raise `ChannelNotFoundError` before processing |
| GPU not available | Cellpose falls back to CPU automatically when `gpu=True` but no GPU |
| Labels with non-contiguous IDs | `regionprops` handles this correctly |
| regionprops centroid is (row, col) | Swap to (x=col, y=row) in LabelProcessor |
| Single-pixel cell | perimeter=0, circularity=0.0 (guard in LabelProcessor) |
| `_seg.npy` missing "masks" key | Raise `ValueError` with clear message |
| `_seg.npy` with `allow_pickle=True` | Required for Cellpose format; only load user-specified files |
| No regions match filter | Raise `ValueError` before creating segmentation run |
| Empty regions list in experiment | Raise `ValueError` with clear message |
| Imported labels shape != image shape | Raise `ValueError` with both shapes in message |
| Cellpose fails mid-batch | Per-region commit: regions 1..N-1 saved, failed region logged as warning |
| `pixel_size_um` is None | Segmentation proceeds; `area_um2` set to None; no warning |
| Cellpose not installed | `ImportError` with install instructions at `_get_model()` call |
| `diameter` is 0 or negative | Validate in `SegmentationParams.__post_init__`: must be > 0 or None |

## Acceptance Criteria

### Functional
- [ ] Can run Cellpose on any channel from ExperimentStore
- [ ] Label images stored in `labels.zarr` with correct NGFF metadata
- [ ] Cell records (centroid, bbox, area, perimeter, circularity) in SQLite
- [ ] Segmentation run logged with model name and parameters
- [ ] Can import pre-existing label images (TIFF and `_seg.npy`)
- [ ] `SegmentationEngine.run()` works with workflow engine contract
- [ ] CLI `percell3 segment -e exp --channel DAPI` works
- [ ] CLI `percell3 import-labels -e exp --labels mask.tif --region r1 --condition ctrl` works

### Non-Functional
- [ ] Memory: processes one region at a time, no full-experiment image loading
- [ ] No Cellpose import at module level (lazy only)
- [ ] All public functions have type hints and Google-style docstrings
- [ ] Tests pass without GPU (synthetic images + mock segmenter for unit tests)
- [ ] `time percell3 --help` completes in <500ms (no cellpose import at startup)

### Quality Gates
- [ ] All existing tests still pass
- [ ] New tests: ~30 covering all acceptance tests from spec + edge cases
- [ ] `mypy` clean on new files
- [ ] No forbidden dependencies (readlif, tifffile, click in domain code)

## What This Module Does NOT Include (Deferred to Module 3b)

- napari viewer integration
- cellpose-napari plugin configuration
- Interactive label editing
- Native Cellpose GUI launch
- Any Qt/GUI dependencies

These are all in Module 3b: napari Viewer + Segmentation Integration.

## Files Summary

| File | Action | Phase |
|------|--------|-------|
| `src/percell3/segment/__init__.py` | MODIFY — exports + SegmentationEngine | 1, 4 |
| `src/percell3/segment/base_segmenter.py` | CREATE — ABC + SegmentationParams + SegmentationResult | 1 |
| `src/percell3/segment/label_processor.py` | CREATE — regionprops extraction | 2 |
| `src/percell3/segment/cellpose_adapter.py` | CREATE — Cellpose wrapper | 3 |
| `src/percell3/segment/roi_import.py` | CREATE — label import (_seg.npy, TIFF) | 5 |
| `src/percell3/cli/segment_cmd.py` | CREATE — Click commands (segment + import-labels) | 6 |
| `src/percell3/cli/main.py` | MODIFY — replace stub with real import | 6 |
| `src/percell3/cli/menu.py` | MODIFY — enable segment menu item | 6 |
| `tests/test_segment/__init__.py` | CREATE | 1 |
| `tests/test_segment/conftest.py` | CREATE — fixtures | 2 |
| `tests/test_segment/test_base_segmenter.py` | CREATE | 1 |
| `tests/test_segment/test_label_processor.py` | CREATE | 2 |
| `tests/test_segment/test_cellpose_adapter.py` | CREATE | 3 |
| `tests/test_segment/test_engine.py` | CREATE | 4 |
| `tests/test_segment/test_roi_import.py` | CREATE | 5 |
| `tests/test_cli/test_segment.py` | CREATE | 6 |

## References

### Internal
- Brainstorm: `docs/brainstorms/2026-02-13-cellpose-segmentation-workflow-brainstorm.md`
- Spec: `docs/03-segment/spec.md`
- CLAUDE.md: `docs/03-segment/CLAUDE.md`
- Acceptance tests: `docs/03-segment/acceptance-tests.md`
- Architecture: `docs/00-overview/architecture.md`
- Data model: `docs/00-overview/data-model.md`
- ExperimentStore: `src/percell3/core/experiment_store.py`
- CellRecord model: `src/percell3/core/models.py:36-53`
- RegionInfo model: `src/percell3/core/models.py:22-34`
- Schema: `src/percell3/core/schema.py`
- Queries (update cell count): `src/percell3/core/queries.py:316-325`
- Workflow contract: `src/percell3/workflow/defaults.py:107-147`
- CLI stub: `src/percell3/cli/stubs.py:21`
- IO engine pattern: `src/percell3/io/engine.py` (reference for pipeline structure)

### Learnings
- Integer overflow: `docs/solutions/logic-errors/io-module-p1-z-projection-and-input-validation-fixes.md`
- Integration patterns: `docs/solutions/integration-issues/cli-io-dual-mode-review-fixes.md`
- Input validation: `docs/solutions/security-issues/core-module-p1-security-correctness-fixes.md`
- CLI patterns: `docs/solutions/architecture-decisions/cli-module-code-review-findings.md`
