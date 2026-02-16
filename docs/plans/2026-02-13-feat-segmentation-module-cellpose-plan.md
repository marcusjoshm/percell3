---
title: "feat: Segmentation Module with Cellpose Integration"
type: feat
date: 2026-02-13
module: segment
---

# Segmentation Module with Cellpose Integration (Module 3)

## Overview

Build the segmentation engine for PerCell 3, wrapping Cellpose behind an abstract
interface. The module reads images from ExperimentStore, runs cell segmentation,
stores integer label images in `labels.zarr`, and populates the `cells` table in
SQLite with extracted cell properties (centroid, bounding box, area, perimeter,
circularity).

## Problem Statement / Motivation

PerCell 3 currently imports TIFF images into experiments (Module 2: IO) but cannot
segment cells. Users need to:

1. Run Cellpose on any channel (DAPI, GFP, etc.) to detect cell boundaries
2. Store label images alongside raw images in the same experiment
3. Extract quantitative cell properties for downstream analysis
4. Import pre-existing segmentations from Cellpose GUI or ImageJ

The architecture requires Cellpose to be behind an abstract adapter (hexagonal
architecture), so future segmentation tools (StarDist, Mesmer) can be swapped in
without changing domain logic.

## Dependencies & Prerequisites

- **Module 1 (Core)**: Complete. ExperimentStore provides `read_image_numpy()`,
  `write_labels()`, `add_cells()`, `add_segmentation_run()`.
- **cellpose>=3.0**: Already in `pyproject.toml`
- **scikit-image>=0.21**: Already in `pyproject.toml` (for `regionprops`)
- **scipy>=1.10**: Already in `pyproject.toml`
- **Workflow contract**: `percell3.segment.SegmentationEngine` with `.run(store, channel=, model=, diameter=)` method (from `workflow/defaults.py:140-143`)

No dependency on IO, CLI, or Workflow modules.

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
├── base_segmenter.py        # ABC interface
├── cellpose_adapter.py      # Cellpose wrapper with model caching
├── label_processor.py       # Label image -> CellRecord extraction
└── roi_import.py            # Import pre-existing labels/ROIs

tests/test_segment/
├── __init__.py
├── conftest.py              # Shared fixtures
├── test_base_segmenter.py   # Interface contract tests
├── test_cellpose_adapter.py # Cellpose integration (may need GPU mark)
├── test_label_processor.py  # Property extraction tests
├── test_roi_import.py       # ROI import tests
└── test_engine.py           # End-to-end pipeline tests
```

## Implementation Phases

### Phase 1: Foundation — SegmentationParams + BaseSegmenter

**Files**: `base_segmenter.py`, `__init__.py`

- [ ] Create `SegmentationParams` frozen dataclass:
  ```python
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
- [ ] Create `BaseSegmenter` ABC with:
  - `segment(image: np.ndarray, params: SegmentationParams) -> np.ndarray`
  - `segment_batch(images: list[np.ndarray], params: SegmentationParams) -> list[np.ndarray]`
- [ ] Add `__post_init__` validation: `min_size >= 0`, `0 <= flow_threshold <= 3`, `model_name` not empty
- [ ] Export from `__init__.py`

**Tests** (`test_base_segmenter.py`):
- [ ] `SegmentationParams` defaults are correct
- [ ] Validation rejects invalid `min_size`, `flow_threshold`
- [ ] Cannot instantiate `BaseSegmenter` directly (ABC)

---

### Phase 2: LabelProcessor — Cell Property Extraction

**File**: `label_processor.py`

- [ ] Create `LabelProcessor` class with `extract_cells()` method:
  ```python
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
  - `centroid_x`, `centroid_y` from `prop.centroid` (note: regionprops returns `(row, col)` = `(y, x)`, must swap)
  - `bbox_x, bbox_y, bbox_w, bbox_h` from `prop.bbox` (`min_row, min_col, max_row, max_col`)
  - `area_pixels` from `prop.area`
  - `area_um2 = area_pixels * pixel_size_um**2` (if pixel_size provided)
  - `perimeter` from `prop.perimeter`
  - `circularity = 4 * pi * area / perimeter**2` (guard: if perimeter == 0, circularity = 0)
- [ ] Return `list[CellRecord]` (import from `percell3.core.models`)
- [ ] Handle empty label image (no cells) -> return empty list

**Tests** (`test_label_processor.py`):
- [ ] Known 30x30 square: area=900, bbox correct, centroid correct
- [ ] Two objects: returns 2 CellRecords with correct label_values
- [ ] With pixel_size_um: area_um2 = area_pixels * 0.65^2
- [ ] Without pixel_size_um: area_um2 is None
- [ ] Empty label image: returns empty list
- [ ] Circularity of circle ≈ 1.0 (within tolerance)
- [ ] Zero-perimeter guard: circularity = 0

---

### Phase 3: CellposeAdapter

**File**: `cellpose_adapter.py`

- [ ] Create `CellposeAdapter(BaseSegmenter)`:
  ```python
  class CellposeAdapter(BaseSegmenter):
      def __init__(self) -> None:
          self._model_cache: dict[tuple[str, bool], Any] = {}

      def _get_model(self, model_name: str, gpu: bool) -> Any:
          key = (model_name, gpu)
          if key not in self._model_cache:
              from cellpose import models
              self._model_cache[key] = models.Cellpose(
                  model_type=model_name, gpu=gpu,
              )
          return self._model_cache[key]
  ```
- [ ] `segment()`: call `model.eval()` with params, return `masks.astype(np.int32)`
- [ ] `segment_batch()`: call `model.eval()` with list of images
- [ ] Lazy `from cellpose import models` in `_get_model()` (not at module level)
- [ ] Handle Cellpose returning 0 cells: return all-zero label array

**Tests** (`test_cellpose_adapter.py`):
- [ ] Synthetic image with 2 bright disks: detects >= 2 cells
- [ ] Output dtype is `np.int32`
- [ ] Output shape matches input shape
- [ ] Model caching: second call with same params doesn't reimport
- [ ] Mark GPU-dependent tests with `@pytest.mark.slow` or `@pytest.mark.gpu`

---

### Phase 4: SegmentationEngine — Pipeline Orchestration

**File**: Update `__init__.py` with `SegmentationEngine` class

- [ ] Create `SegmentationEngine`:
  ```python
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
- [ ] Pipeline steps:
  1. Create `SegmentationParams` from kwargs
  2. Instantiate `CellposeAdapter` if no segmenter provided (default)
  3. Get regions to segment (all, or filtered by `regions`/`condition`)
  4. Call `store.add_segmentation_run(channel, model, params_dict)` -> `run_id`
  5. For each region:
     - `image = store.read_image_numpy(region.name, region.condition, channel)`
     - `labels = segmenter.segment(image, params)`
     - `store.write_labels(region.name, region.condition, labels, run_id)`
     - `cells = LabelProcessor().extract_cells(labels, region.id, run_id, region.pixel_size_um)`
     - `store.add_cells(cells)`
     - Call `progress_callback(i+1, total, region.name)` if provided
  6. Return `SegmentationResult` with run_id, cell_count, regions_processed
- [ ] Create `SegmentationResult` frozen dataclass:
  ```python
  @dataclass(frozen=True)
  class SegmentationResult:
      run_id: int
      cell_count: int
      regions_processed: int
      warnings: list[str] = field(default_factory=list)
  ```
- [ ] Handle no-cells case: log warning, still write empty labels, cell_count=0
- [ ] Handle missing channel: raise `ChannelNotFoundError` (from core)

**Tests** (`test_engine.py`):
- [ ] End-to-end with mock segmenter: labels stored, cells in DB
- [ ] Progress callback called once per region
- [ ] Missing channel raises `ChannelNotFoundError`
- [ ] Region filtering: only specified regions processed
- [ ] Empty segmentation (0 cells): warning in result, labels stored as zeros
- [ ] Re-segmentation: new run_id, old cells preserved

---

### Phase 5: RoiImporter — Pre-Existing Labels

**File**: `roi_import.py`

- [ ] Create `RoiImporter`:
  ```python
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
  ```
- [ ] Steps:
  1. Validate labels dtype (must be integer)
  2. Cast to int32 if needed
  3. Create segmentation run with `model_name=source`
  4. Write labels to store
  5. Extract cells via LabelProcessor
  6. Insert cells
  7. Return run_id
- [ ] `import_imagej_rois()` — optional stretch goal, can stub initially

**Tests** (`test_roi_import.py`):
- [ ] Import 2-cell label image: cells in DB match
- [ ] Labels round-trip: stored labels match input
- [ ] Non-integer labels dtype raises ValueError
- [ ] Zero-cell label image: run created, 0 cells

---

### Phase 6: CLI Integration

**File**: Replace stub in `src/percell3/cli/stubs.py` with real command

- [ ] Create `src/percell3/cli/segment_cmd.py`:
  ```python
  @click.command("segment")
  @click.option("-e", "--experiment", required=True, type=click.Path(exists=True))
  @click.option("-c", "--channel", default="DAPI")
  @click.option("--model", default="cyto3", type=click.Choice(["cyto3", "nuclei", "cyto2"]))
  @click.option("--diameter", default=None, type=float)
  @click.option("--condition", default=None)
  @click.option("--regions", multiple=True)
  @click.option("--yes", "-y", is_flag=True)
  ```
- [ ] Replace stub import in `main.py`
- [ ] Add menu item handler in `menu.py` (option 3: "Segment cells")
- [ ] Progress bar via `make_progress()`

**Tests** (`tests/test_cli/test_segment.py`):
- [ ] `percell3 segment -e exp --channel DAPI --yes` with mock segmenter
- [ ] Help text shows all options
- [ ] Missing experiment raises error

---

## Dependency Graph

```
Phase 1 (Params + ABC)  ───┐
Phase 2 (LabelProcessor) ──├──▶ Phase 4 (Engine) ──▶ Phase 6 (CLI)
Phase 3 (CellposeAdapter) ─┘                    \
                                                  Phase 5 (ROI Import)
```

Phases 1-3 are independent. Phase 4 depends on all three. Phases 5-6 depend on 4.

## Institutional Learnings to Apply

From `docs/solutions/`:

1. **Integer overflow**: Use `dtype=np.float64` when computing `area_um2`, `circularity`, and any accumulation operations. Never rely on input dtype for arithmetic.

2. **Memory streaming**: Process regions one at a time (already the plan). Never load all region images into a list.

3. **Explicit error on unknown values**: Validate `model_name` against known models. Raise `ValueError` for unknowns — no silent fallbacks.

4. **Input validation at boundaries**: Channel names validated by ExperimentStore. Params validated in `SegmentationParams.__post_init__`.

5. **Adapter pattern**: Cellpose import is lazy (inside `_get_model()`). Domain code (`SegmentationEngine`) never imports Cellpose directly — always through `BaseSegmenter` interface.

## Edge Cases

| Scenario | Handling |
|----------|----------|
| Image with 0 cells detected | Store all-zero labels, log warning, cell_count=0 |
| Very large image (>4096px) | Process as single image (Cellpose handles tiling internally) |
| Re-segmentation of same region | New `segmentation_run`, old cells preserved |
| Channel doesn't exist | Raise `ChannelNotFoundError` before processing |
| GPU not available | Cellpose falls back to CPU automatically when `gpu=True` but no GPU found |
| Labels with non-contiguous IDs | `regionprops` handles this correctly |
| regionprops centroid is (row, col) | Swap to (x=col, y=row) in LabelProcessor |

## Acceptance Criteria

### Functional
- [ ] Can run Cellpose on any channel from ExperimentStore
- [ ] Label images stored in `labels.zarr` with correct NGFF metadata
- [ ] Cell records (centroid, bbox, area, perimeter, circularity) in SQLite
- [ ] Segmentation run logged with model name and parameters
- [ ] Can import pre-existing label images
- [ ] `SegmentationEngine.run()` works with workflow engine contract
- [ ] CLI `percell3 segment -e exp --channel DAPI` works

### Non-Functional
- [ ] Memory: processes one region at a time, no full-experiment image loading
- [ ] No Cellpose import at module level (lazy only)
- [ ] All public functions have type hints and Google-style docstrings
- [ ] Tests pass without GPU (synthetic images + mock segmenter for unit tests)

### Quality Gates
- [ ] All existing 373 tests still pass
- [ ] New tests: ~25-30 covering all 5 acceptance tests from spec + edge cases
- [ ] `mypy` clean on new files
- [ ] No forbidden dependencies (readlif, tifffile, click in domain code)

## Files Summary

| File | Action | Phase |
|------|--------|-------|
| `src/percell3/segment/__init__.py` | MODIFY — exports + SegmentationEngine | 1, 4 |
| `src/percell3/segment/base_segmenter.py` | CREATE — ABC + SegmentationParams | 1 |
| `src/percell3/segment/label_processor.py` | CREATE — regionprops extraction | 2 |
| `src/percell3/segment/cellpose_adapter.py` | CREATE — Cellpose wrapper | 3 |
| `src/percell3/segment/roi_import.py` | CREATE — label/ROI import | 5 |
| `src/percell3/cli/segment_cmd.py` | CREATE — Click command | 6 |
| `src/percell3/cli/main.py` | MODIFY — replace stub with real import | 6 |
| `src/percell3/cli/menu.py` | MODIFY — enable segment menu item | 6 |
| `tests/test_segment/conftest.py` | CREATE — fixtures | 2 |
| `tests/test_segment/test_base_segmenter.py` | CREATE | 1 |
| `tests/test_segment/test_label_processor.py` | CREATE | 2 |
| `tests/test_segment/test_cellpose_adapter.py` | CREATE | 3 |
| `tests/test_segment/test_engine.py` | CREATE | 4 |
| `tests/test_segment/test_roi_import.py` | CREATE | 5 |
| `tests/test_cli/test_segment.py` | CREATE | 6 |

## References

### Internal
- Spec: `docs/03-segment/spec.md`
- CLAUDE.md: `docs/03-segment/CLAUDE.md`
- Acceptance tests: `docs/03-segment/acceptance-tests.md`
- Architecture: `docs/00-overview/architecture.md`
- Data model: `docs/00-overview/data-model.md`
- ExperimentStore: `src/percell3/core/experiment_store.py`
- Schema: `src/percell3/core/schema.py`
- Workflow contract: `src/percell3/workflow/defaults.py:107-147`
- CLI stub: `src/percell3/cli/stubs.py:129`
- IO engine pattern: `src/percell3/io/engine.py` (reference for pipeline structure)

### Learnings
- Integer overflow: `docs/solutions/logic-errors/io-module-p1-z-projection-and-input-validation-fixes.md`
- Integration patterns: `docs/solutions/integration-issues/cli-io-dual-mode-review-fixes.md`
- Input validation: `docs/solutions/security-issues/core-module-p1-security-correctness-fixes.md`
