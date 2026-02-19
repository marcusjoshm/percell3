---
title: "feat: Thresholding module with cell grouping, napari QC, and particle analysis"
type: feat
date: 2026-02-19
brainstorm: docs/brainstorms/2026-02-19-thresholding-module-brainstorm.md
---

# Thresholding Module — Cell Grouping, Napari QC, Particle Analysis

## Overview

Build a three-engine thresholding module for analyzing polyclonal cell populations. The workflow: (1) group cells by expression level using GMM, (2) threshold each group with napari live preview + ROI, (3) analyze particles within threshold masks with full morphometrics.

This is the core analysis workflow that replaces manual ImageJ thresholding from PerCell 2.

## Problem Statement

Polyclonal populations express fluorescent proteins at different levels. Standard Otsu thresholding fails because pixel intensities vary across cells. Grouping cells by expression level creates subpopulations where Otsu works correctly. The manual QC step (ROI-restricted Otsu, accept/skip) is critical and must be preserved.

## Architecture

Three composable engines following the `SegmentationEngine` pattern:

```
CellGrouper          ThresholdEngine (enhanced)     ParticleAnalyzer
  GMM + BIC    →     napari preview + ROI       →   scipy.ndimage.label
  cell tags           masks.zarr                     particles table
                                                     summary measurements
```

All engines use ExperimentStore public API only (hexagonal architecture — never import `queries` or access `store._conn`).

## Data Model Changes

### New `particles` table

```sql
CREATE TABLE IF NOT EXISTS particles (
    id INTEGER PRIMARY KEY,
    cell_id INTEGER NOT NULL REFERENCES cells(id),
    threshold_run_id INTEGER NOT NULL REFERENCES threshold_runs(id),
    label_value INTEGER NOT NULL,
    centroid_x REAL NOT NULL,
    centroid_y REAL NOT NULL,
    bbox_x INTEGER NOT NULL,
    bbox_y INTEGER NOT NULL,
    bbox_w INTEGER NOT NULL,
    bbox_h INTEGER NOT NULL,
    area_pixels REAL NOT NULL,
    area_um2 REAL,
    perimeter REAL,
    circularity REAL,
    eccentricity REAL,
    solidity REAL,
    major_axis_length REAL,
    minor_axis_length REAL,
    mean_intensity REAL,
    max_intensity REAL,
    integrated_intensity REAL,
    UNIQUE(cell_id, threshold_run_id, label_value)
);
CREATE INDEX IF NOT EXISTS idx_particles_cell ON particles(cell_id);
CREATE INDEX IF NOT EXISTS idx_particles_run ON particles(threshold_run_id);
```

### New `ParticleRecord` dataclass

```python
# src/percell3/core/models.py
@dataclass(frozen=True)
class ParticleRecord:
    cell_id: int
    threshold_run_id: int
    label_value: int
    centroid_x: float
    centroid_y: float
    bbox_x: int
    bbox_y: int
    bbox_w: int
    bbox_h: int
    area_pixels: float
    area_um2: float | None = None
    perimeter: float | None = None
    circularity: float | None = None
    eccentricity: float | None = None
    solidity: float | None = None
    major_axis_length: float | None = None
    minor_axis_length: float | None = None
    mean_intensity: float | None = None
    max_intensity: float | None = None
    integrated_intensity: float | None = None
```

### Particle label images in zarr

Store in `masks.zarr` at path `{condition}/{bio_rep}/{fov}/particles_{channel}` as int32. Each particle gets a unique integer ID per FOV. Reuses `LABEL_COMPRESSOR` and `LABEL_CHUNKS`.

### Per-cell summary measurements

Stored in existing `measurements` table with the thresholding channel. Metric names:
- `particle_count` — number of particles in the cell
- `total_particle_area` — sum of all particle areas (pixels)
- `mean_particle_area` — mean particle area
- `max_particle_area` — largest particle area
- `particle_coverage_fraction` — total particle area / cell area

### Group tag naming convention

Tags follow: `group:{channel}:{metric}:g{N}` (e.g., `group:GFP:mean_intensity:g1`). Groups are ordered by ascending metric value so g1 = lowest expression. Namespacing enables cleanup on re-grouping.

### Threshold run context

Store FOV and group info in the existing `parameters` JSON column of `threshold_runs`:
```json
{
  "fov_name": "fov_1",
  "condition": "control",
  "group_tag": "group:GFP:mean_intensity:g1",
  "roi": [[x1, y1, x2, y2]]
}
```

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Otsu on group image | Exclude zeroed pixels (masked array) | Zeros from non-group cells would skew histogram |
| ROI semantics | Restricts Otsu computation only; threshold applied to full group image | Matches ImageJ workflow |
| ROI shapes | Rectangle only | Simple, matches ImageJ |
| Multiple ROIs | Union of rectangles | Flexible without complexity |
| Napari sessions | One per FOV, swap layers between groups | Avoids repeated 2-5s launch overhead |
| Window close without decision | Treat as skip | Safe default, no data loss |
| Cancel mid-workflow | Same as "skip remaining" — saves accepted masks | Preserves partial progress |
| Skipped groups | Store particle_count=0 measurements | Distinguishes "no features" from "not measured" |
| Min particle size | Default 5 pixels, configurable | Filters 1-pixel noise |
| Particle intensity | Thresholding channel only (initially) | Multi-channel can be added later |
| Min cells for GMM | 10 cells; below that, single group with warning | GMM unreliable with very few data points |
| GMM 1 component | Still show napari; log "homogeneous population" | User should still QC |
| GMM params | covariance_type='full', 1 to min(10, n//5) components, n_init=5 | Robust default |
| Measurements prerequisite | Error if grouping metric not measured (except area from cells table) | Explicit over implicit |
| Multi-FOV | Batch loop with per-FOV napari review + "skip remaining FOVs" | Matches SegmentationEngine pattern |
| Threshold mask + cell | Intersection (AND) | Particles strictly within cell boundaries |
| Re-thresholding | Delete old particles + masks, clean slate | Matches re-segmentation pattern |

---

## Implementation Phases

### Phase 1: Data Layer

Add `particles` table, `ParticleRecord`, and ExperimentStore methods.

#### Files to modify

| File | Changes |
|------|---------|
| `src/percell3/core/schema.py` | Add `particles` table DDL, indexes, update `EXPECTED_TABLES` |
| `src/percell3/core/models.py` | Add `ParticleRecord` dataclass |
| `src/percell3/core/queries.py` | Add `insert_particles()`, `select_particles()`, `delete_particles_for_fov()`, `delete_particles_for_threshold_run()`, `select_threshold_runs()`, `delete_tags_by_prefix()` |
| `src/percell3/core/experiment_store.py` | Add `add_particles()`, `get_particles()`, `delete_particles_for_fov()`, `get_threshold_runs()`, `delete_tags_by_prefix()`, `write_particle_labels()`, `read_particle_labels()` |
| `src/percell3/core/zarr_io.py` | Add `particle_label_group_path()`, `write_particle_labels()`, `read_particle_labels()` |

#### Tasks

- [ ] Add `particles` table to `schema.py` DDL and `EXPECTED_TABLES`
- [ ] Add `ParticleRecord` to `models.py`
- [ ] Add particle queries to `queries.py`: `insert_particles()` (bulk), `select_particles()` (with filters), `delete_particles_for_fov()`, `delete_particles_for_threshold_run()`
- [ ] Add `select_threshold_runs()` to `queries.py` (modeled on `select_segmentation_runs()`)
- [ ] Add `delete_tags_by_prefix()` to `queries.py`
- [ ] Add zarr path helper `particle_label_group_path()` and I/O functions to `zarr_io.py`
- [ ] Add ExperimentStore wrapper methods: `add_particles()`, `get_particles()`, `delete_particles_for_fov()`, `get_threshold_runs()`, `delete_tags_by_prefix()`, `write_particle_labels()`, `read_particle_labels()`
- [ ] Write tests for all new queries and store methods
- [ ] Run full test suite

### Phase 2: CellGrouper

GMM-based cell grouping engine. Pure computation — no napari dependency.

#### Files to create/modify

| File | Changes |
|------|---------|
| `src/percell3/measure/cell_grouper.py` | **New file** — `CellGrouper` class |
| `tests/test_measure/test_cell_grouper.py` | **New file** — Tests |

#### CellGrouper API

```python
# src/percell3/measure/cell_grouper.py

@dataclass(frozen=True)
class GroupingResult:
    n_groups: int
    group_labels: np.ndarray        # int array, one per cell
    group_means: list[float]        # mean metric value per group (ascending)
    bic_scores: list[float]         # BIC for each tested component count
    tag_names: list[str]            # e.g., ["group:GFP:mean_intensity:g1", ...]

MIN_CELLS_FOR_GMM = 10

class CellGrouper:
    def group_cells(
        self,
        store: ExperimentStore,
        fov: str,
        condition: str,
        channel: str,
        metric: str,
        bio_rep: str | None = None,
        max_components: int = 10,
    ) -> GroupingResult:
        """Group cells by metric value using GMM with BIC."""
        # 1. Get cells for this FOV
        # 2. Get metric values (from measurements, or area from cells table)
        # 3. If < MIN_CELLS_FOR_GMM: single group with warning
        # 4. Fit GMM with BIC for 1..min(max_components, n_cells//5)
        # 5. Select best by lowest BIC
        # 6. Predict group labels, sort by ascending mean
        # 7. Create tags and tag cells
        # 8. Return GroupingResult
```

#### Tasks

- [ ] Create `src/percell3/measure/cell_grouper.py` with `CellGrouper` and `GroupingResult`
- [ ] Implement GMM + BIC fitting with ascending group ordering
- [ ] Handle edge cases: 0 cells (ValueError), <10 cells (single group), 1 GMM component
- [ ] Handle `area` metric from cells table vs. other metrics from measurements table
- [ ] Write tests: happy path, few cells fallback, 1 component, missing measurements error, area from cells table
- [ ] Run tests

### Phase 3: ThresholdEngine Enhancement + Napari QC Viewer

Extend ThresholdEngine with group-aware thresholding. Create napari threshold viewer.

#### Files to create/modify

| File | Changes |
|------|---------|
| `src/percell3/measure/thresholding.py` | Add `threshold_group()` method |
| `src/percell3/measure/threshold_viewer.py` | **New file** — napari threshold QC viewer |
| `tests/test_measure/test_thresholding.py` | Add tests for `threshold_group()` |
| `tests/test_measure/test_threshold_viewer.py` | **New file** — viewer tests (mock napari) |

#### ThresholdEngine.threshold_group() API

```python
def threshold_group(
    self,
    store: ExperimentStore,
    fov: str,
    condition: str,
    channel: str,
    cell_ids: list[int],
    labels: np.ndarray,
    image: np.ndarray,
    method: str = "otsu",
    roi: list[tuple[int, int, int, int]] | None = None,
    bio_rep: str | None = None,
) -> ThresholdResult | None:
    """Threshold a group of cells within a FOV.

    Creates a group image (full FOV with only specified cells visible),
    computes threshold using masked pixels only (excluding zeroed regions),
    and stores the binary mask.

    Returns None if the user skipped this group (no mask stored).
    """
```

#### Napari Threshold Viewer

```python
# src/percell3/measure/threshold_viewer.py

@dataclass
class ThresholdDecision:
    accepted: bool
    threshold_value: float
    roi: list[tuple[int, int, int, int]] | None

def launch_threshold_viewer(
    group_image: np.ndarray,
    cell_mask: np.ndarray,
    group_name: str,
    fov_name: str,
    initial_threshold: float | None = None,
) -> ThresholdDecision:
    """Open napari with live threshold preview for a cell group.

    Shows:
    - Group image (channel data, non-group cells zeroed)
    - Threshold preview overlay (updates live with ROI changes)
    - Dock widget with Accept/Skip/Skip Remaining buttons

    Returns:
        ThresholdDecision with accepted=True/False and threshold_value.
        Returns ThresholdDecision(accepted=False, ...) if window closed.
    """
```

#### Napari Dock Widget

A minimal `QWidget` with three buttons:
- **Accept** — saves the current threshold, closes viewer for this group
- **Skip** — no mask saved, continues to next group
- **Skip Remaining** — no mask for this or subsequent groups, proceed to particle analysis

The widget also displays:
- Current threshold value (updates live)
- Group name and FOV name
- Positive pixel count / fraction

#### Live Preview Mechanism

1. Add a `Shapes` layer for rectangle ROI drawing
2. Connect to `shapes.events.data` to detect ROI changes
3. On each ROI change: compute Otsu within ROI + cell mask intersection
4. Update the `Labels` preview layer with the new binary mask
5. Update threshold value display in the dock widget

#### Tasks

- [ ] Add `threshold_group()` to `ThresholdEngine` — creates group image, computes masked Otsu, stores mask
- [ ] Create `threshold_viewer.py` with `launch_threshold_viewer()` and `ThresholdDecision`
- [ ] Implement napari dock widget with Accept/Skip/Skip Remaining buttons
- [ ] Implement live Otsu recomputation on ROI change
- [ ] Handle window close without decision (treat as skip)
- [ ] Write tests for `threshold_group()` (group image creation, masked Otsu, mask storage)
- [ ] Write tests for viewer logic with mocked napari (ThresholdDecision return values)
- [ ] Run tests

### Phase 4: ParticleAnalyzer

Connected component analysis + full morphometrics.

#### Files to create/modify

| File | Changes |
|------|---------|
| `src/percell3/measure/particle_analyzer.py` | **New file** — `ParticleAnalyzer` class |
| `tests/test_measure/test_particle_analyzer.py` | **New file** — Tests |

#### ParticleAnalyzer API

```python
# src/percell3/measure/particle_analyzer.py

PARTICLE_SUMMARY_METRICS = [
    "particle_count",
    "total_particle_area",
    "mean_particle_area",
    "max_particle_area",
    "particle_coverage_fraction",
]

@dataclass(frozen=True)
class ParticleAnalysisResult:
    threshold_run_id: int
    particles: list[ParticleRecord]
    summary_measurements: list[MeasurementRecord]
    particle_label_image: np.ndarray  # int32, full FOV
    cells_analyzed: int
    total_particles: int

class ParticleAnalyzer:
    def __init__(self, min_particle_area: int = 5) -> None:
        self._min_area = min_particle_area

    def analyze_fov(
        self,
        store: ExperimentStore,
        fov: str,
        condition: str,
        channel: str,
        threshold_run_id: int,
        cell_ids: list[int],
        bio_rep: str | None = None,
    ) -> ParticleAnalysisResult:
        """Analyze particles within threshold mask for cells in a FOV.

        For each cell:
        1. Crop label + threshold mask to cell bbox
        2. Intersect: particle_mask = threshold_mask AND (label == cell_label)
        3. Find connected components (scipy.ndimage.label)
        4. Filter by min_particle_area
        5. Measure morphometrics (skimage.measure.regionprops)
        6. Build ParticleRecord for each particle
        7. Build per-cell summary MeasurementRecords

        For skipped cells (no threshold mask): stores particle_count=0.
        """
```

#### Per-cell processing (follows Measurer bbox pattern)

```python
for _, cell in cells_df.iterrows():
    bx, by, bw, bh = cell.bbox_x, cell.bbox_y, cell.bbox_w, cell.bbox_h
    label_crop = labels[by:by+bh, bx:bx+bw]
    mask_crop = threshold_mask[by:by+bh, bx:bx+bw]
    image_crop = channel_image[by:by+bh, bx:bx+bw]

    cell_mask = label_crop == cell.label_value
    particle_mask = mask_crop & cell_mask

    particle_labels, n_particles = scipy.ndimage.label(particle_mask)
    props = skimage.measure.regionprops(particle_labels, intensity_image=image_crop)

    for prop in props:
        if prop.area < self._min_area:
            continue
        # Build ParticleRecord with morphometrics
```

#### Tasks

- [ ] Create `src/percell3/measure/particle_analyzer.py` with `ParticleAnalyzer` and `ParticleAnalysisResult`
- [ ] Implement per-cell particle detection using scipy.ndimage.label
- [ ] Implement morphometrics extraction via skimage.measure.regionprops
- [ ] Implement min_particle_area filtering
- [ ] Implement per-cell summary measurements (particle_count, total_particle_area, etc.)
- [ ] Build per-FOV particle label image (assign unique IDs across all cells)
- [ ] Handle cells with no threshold mask (skipped groups): particle_count=0
- [ ] Write tests: single cell with particles, multiple cells, no particles, min area filter, summary metrics
- [ ] Run tests

### Phase 5: CLI Integration

Enable menu item 6 with the full thresholding workflow.

#### Files to modify

| File | Changes |
|------|---------|
| `src/percell3/cli/menu.py` | Enable item 6, add `_apply_threshold()` handler |

#### CLI Workflow

```
_apply_threshold(state):
  1. store = state.require_experiment()
  2. Channel selection for grouping (numbered_select_one)
  3. Metric selection for grouping (numbered_select_one: mean_intensity, median_intensity, etc.)
  4. Channel selection for thresholding (numbered_select_one, default=same as grouping)
  5. FOV table + selection (reuse _show_fov_status_table / _select_fovs_from_table)
  6. Confirmation summary
  7. For each FOV:
     a. Run CellGrouper → show group summary table
     b. For each group: open napari threshold viewer
     c. Run ParticleAnalyzer on accepted groups
     d. Show per-FOV results
  8. Show overall results summary
```

#### Tasks

- [ ] Enable menu item 6 in `menu.py`: change `None` to `_apply_threshold` and `enabled=True`
- [ ] Implement `_apply_threshold()` handler following the segmentation menu pattern
- [ ] Add grouping channel + metric selection prompts
- [ ] Add threshold channel selection prompt (default = grouping channel)
- [ ] Show grouping summary (number of groups, cells per group) before napari
- [ ] Integrate napari threshold viewer in per-group loop
- [ ] Show per-FOV particle analysis results
- [ ] Show overall summary after all FOVs processed
- [ ] Handle "skip remaining FOVs" option
- [ ] Write CLI tests with mocked napari (test prompt flow, not viewer)
- [ ] Run full test suite

### Phase 6: Integration Tests

End-to-end tests that exercise the full pipeline.

#### Files to create

| File | Changes |
|------|---------|
| `tests/test_measure/test_threshold_integration.py` | **New file** — End-to-end tests |

#### Tasks

- [ ] Test: CellGrouper → ThresholdEngine → ParticleAnalyzer full pipeline (mocked napari)
- [ ] Test: re-thresholding replaces old particles and cleans up tags
- [ ] Test: multi-FOV batch processing
- [ ] Test: group with all cells skipped produces particle_count=0
- [ ] Test: particle label image round-trip through zarr
- [ ] Run full test suite — all tests must pass

---

## Acceptance Criteria

### Functional

- [ ] `CellGrouper.group_cells()` fits GMM with BIC, assigns cells to groups via tags
- [ ] GMM gracefully handles <10 cells (single group) and 1 component (logs warning)
- [ ] `ThresholdEngine.threshold_group()` creates masked group image and computes Otsu excluding zeroed pixels
- [ ] Napari viewer shows live threshold preview, supports rectangle ROI, accept/skip/skip-remaining
- [ ] ROI restricts Otsu computation only; threshold applied to full group image
- [ ] `ParticleAnalyzer.analyze_fov()` finds connected components within cell boundaries
- [ ] Particles filtered by min_area (default 5 pixels)
- [ ] Individual particles stored in `particles` table with full morphometrics
- [ ] Particle label image stored in zarr (int32)
- [ ] Per-cell summary measurements stored: particle_count, total_particle_area, mean_particle_area, max_particle_area, particle_coverage_fraction
- [ ] Re-thresholding deletes old particles, masks, and group tags before re-creating
- [ ] CLI menu item 6 "Apply threshold" works end-to-end

### Architecture

- [ ] No imports of `queries`, `schema`, or `zarr_io` outside of `core/`
- [ ] All store access through public ExperimentStore API
- [ ] Each engine testable independently without the others
- [ ] Frozen dataclasses for all value objects

### Testing

- [ ] Unit tests for CellGrouper, ThresholdEngine, ParticleAnalyzer
- [ ] Integration test for full pipeline
- [ ] Re-thresholding test
- [ ] All existing tests still pass

---

## References

### Internal

- `src/percell3/measure/thresholding.py` — existing ThresholdEngine to extend
- `src/percell3/measure/measurer.py:144` — bbox-optimized per-cell pattern
- `src/percell3/segment/_engine.py:38` — batch FOV processing pattern
- `src/percell3/segment/viewer/_viewer.py:56` — blocking napari pattern
- `src/percell3/core/schema.py:104` — threshold_runs table
- `src/percell3/core/models.py` — CellRecord, MeasurementRecord patterns
- `src/percell3/cli/menu.py:221` — disabled menu item 6 placeholder

### Architecture Guidance

- `docs/solutions/architecture-decisions/segment-module-private-api-encapsulation-fix.md` — hexagonal architecture enforcement
- `docs/00-overview/architecture.md` — system architecture
- `docs/04-measure/spec.md` — measurement module specification
- `docs/brainstorms/2026-02-19-thresholding-module-brainstorm.md` — brainstorm with all design decisions

### Dependencies

- `sklearn.mixture.GaussianMixture` — GMM + BIC
- `skimage.filters.threshold_otsu` — already used
- `scipy.ndimage.label` — connected component labeling
- `skimage.measure.regionprops` — particle morphometrics
- `napari` — already a dependency
