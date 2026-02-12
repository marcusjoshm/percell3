# CLAUDE.md — Module 2: IO (percell3.io)

## Your Task
Build format readers that import microscopy images into the ExperimentStore.
Primary formats: Leica LIF, TIFF directories (PerCell 2 format), and CZI.

## Read First
1. `../00-overview/architecture.md`
2. `../01-core/spec.md` (understand ExperimentStore API you depend on)
3. `./spec.md` (your detailed spec)

## Output Location
- Source: `src/percell3/io/`
- Tests: `tests/test_io/`

## Files to Create
```
src/percell3/io/
├── __init__.py
├── base_reader.py           # Abstract base reader interface
├── lif_reader.py            # LIF -> ExperimentStore (via readlif)
├── tiff_reader.py           # TIFF directory -> ExperimentStore
├── czi_reader.py            # CZI -> ExperimentStore (optional, via aicspylibczi)
├── metadata.py              # Vendor metadata -> OME metadata normalization
└── utils.py                 # Shared utilities (dtype conversion, etc.)
```

## Acceptance Criteria
1. Can import a multi-series LIF file: each series becomes a region with correct channels
2. Can import a PerCell 2 TIFF directory structure preserving condition/region/channel hierarchy
3. Channel names, pixel sizes, and dimensions are correctly extracted from LIF metadata
4. All data written via ExperimentStore API (never directly to Zarr or SQLite)
5. Re-importing the same file does not create duplicates
6. TIFF files with various bit depths (8, 12, 16 bit) are handled correctly

## Dependencies You Can Use
readlif (>=0.6.4), tifffile, aicspylibczi (optional), ome-types, numpy, percell3.core

## Dependencies You Must NOT Use
cellpose, click, scikit-image
