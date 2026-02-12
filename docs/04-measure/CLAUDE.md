# CLAUDE.md — Module 4: Measure (percell3.measure)

## Your Task
Build the measurement engine. Given cell boundaries and any channel, compute
per-cell measurements. Implement thresholding (Otsu, adaptive, manual).

## Read First
1. `../00-overview/architecture.md`
2. `../01-core/spec.md`
3. `./spec.md`

## Output Location
- Source: `src/percell3/measure/`
- Tests: `tests/test_measure/`

## Files to Create
```
src/percell3/measure/
├── __init__.py
├── measurer.py              # Main measurement engine
├── metrics.py               # Built-in metric functions
├── thresholding.py          # Otsu, adaptive, manual -> masks.zarr
└── batch.py                 # Batch measurement across all regions/channels
```

## Acceptance Criteria
1. Can measure mean/max/integrated intensity for any channel using existing labels
2. Can measure a channel that was NOT used for segmentation
3. Measurements stored in SQLite via ExperimentStore.add_measurements()
4. Otsu thresholding produces a binary mask stored in masks.zarr
5. Batch mode measures all cells x all channels efficiently
6. get_measurement_pivot() returns a clean DataFrame for downstream analysis

## Dependencies You Can Use
scikit-image, scipy, numpy, dask, percell3.core

## Dependencies You Must NOT Use
cellpose, readlif, click, rich
