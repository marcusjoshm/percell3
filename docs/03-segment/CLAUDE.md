# CLAUDE.md — Module 3: Segment (percell3.segment)

## Your Task
Build the segmentation engine. Wrap Cellpose behind an abstract interface.
Convert label images into cell records in the database.

## Read First
1. `../00-overview/architecture.md`
2. `../01-core/spec.md`
3. `./spec.md`

## Output Location
- Source: `src/percell3/segment/`
- Tests: `tests/test_segment/`

## Files to Create
```
src/percell3/segment/
├── __init__.py
├── base_segmenter.py       # Abstract segmentation interface
├── cellpose_adapter.py      # Cellpose implementation
├── label_processor.py       # Label image -> CellRecord extraction
└── roi_import.py            # Import ROIs from ImageJ or Cellpose GUI
```

## Acceptance Criteria
1. Can run Cellpose on any channel from the ExperimentStore
2. Label images stored in labels.zarr with correct NGFF metadata
3. Cell records (centroid, bbox, area, perimeter, circularity) extracted and stored in SQLite
4. Segmentation run logged with model name and parameters
5. Can segment on DAPI and use those boundaries for GFP/RFP measurements later
6. Can import pre-existing label images (e.g., from Cellpose GUI)

## Dependencies You Can Use
cellpose, scikit-image, scipy, numpy, percell3.core

## Dependencies You Must NOT Use
readlif, tifffile, click, rich
