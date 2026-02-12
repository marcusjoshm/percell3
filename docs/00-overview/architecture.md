# PerCell 3 — Architecture Overview

## Design Philosophy

PerCell 3 is a **non-linear microscopy analysis workbench**, not a pipeline.
Once you import images and run segmentation, you can measure any channel, apply any threshold, run any plugin, in any order, at any time. The experiment database remembers everything.

## Core Architecture: ExperimentStore

```
     ┌──────────────────────────┐
     │     User (CLI / GUI)     │
     └────────────┬─────────────┘
                  │
     ┌────────────▼─────────────┐
     │    Workflow Engine        │  <- Orchestrates steps (optional)
     └────────────┬─────────────┘
                  │
     ┌────────────▼─────────────┐
     │   ExperimentStore         │  <- THE central object
     │                           │
     │   .db     -> SQLite       │  metadata, cells, measurements
     │   .zarr   -> OME-Zarr     │  images, labels, masks
     │   .query  -> SQL + array  │  combined access
     └────────────┬─────────────┘
                  │
     ┌────────────▼─────────────┐
     │   Adapters (Ports)        │
     │   ├── Cellpose            │
     │   ├── readlif             │
     │   ├── scikit-image        │
     │   └── FLIM-Phasor         │
     └──────────────────────────┘
```

## Module Map

| # | Module | Purpose | Depends On |
|---|--------|---------|------------|
| 1 | `core` | ExperimentStore, SQLite, OME-Zarr I/O | -- |
| 2 | `io` | Format readers: LIF, TIFF, CZI | core |
| 3 | `segment` | Cellpose segmentation -> labels + cells table | core |
| 4 | `measure` | Per-cell measurements + thresholding | core |
| 5 | `plugins` | Plugin system + built-in analysis plugins | core |
| 6 | `workflow` | DAG-based workflow orchestration | core, 2-5 |
| 7 | `cli` | Click command-line interface | core, 2-6 |

## Module Dependency Graph

```
Module 7: CLI
    │
    ├── Module 6: Workflow Engine
    │       │
    │       ├── Module 5: Plugins
    │       │       │
    │       │       └── Module 1: Core <──────────────┐
    │       │                                          │
    │       ├── Module 4: Measure ─────────────────────┤
    │       │                                          │
    │       ├── Module 3: Segment ─────────────────────┤
    │       │                                          │
    │       └── Module 2: IO ──────────────────────────┘
    │
    └── Module 1: Core (everything depends on this)
```

**Build order**: 1 -> (2, 3, 4, 5 in parallel) -> 6 -> 7

## What Changed from PerCell 2

| Concept | PerCell 2 | PerCell 3 |
|---------|-----------|-----------|
| Data storage | Thousands of TIFF files in nested dirs | OME-Zarr (compressed, chunked) |
| Experiment config | config.json + directory names | SQLite database |
| Channel selection | Parsed from filenames/directory names | SQL query on channels table |
| Cell extraction | Individual CELL*.tif files via ImageJ | Label images in OME-Zarr + SQL cell records |
| Measurements | CSV files generated at end | SQL measurements table (queryable anytime) |
| Workflow | Linear pipeline (must run in order) | DAG-based (re-run any step independently) |
| Thresholding | ImageJ macros | Python-native (scikit-image) |
| Plugin system | Hardcoded menu entries | Discoverable Python plugins via entry_points |
| File format support | TIFF only | LIF, TIFF, CZI, OME-TIFF, OME-Zarr |

## Hexagonal Architecture

- **Domain**: ExperimentStore, data models, measurement algorithms
- **Ports**: Abstract interfaces for segmentation, image reading, thresholding
- **Adapters**: Cellpose, readlif, ImageJ (optional), tifffile
- **Application**: Workflow engine, CLI, plugin manager

External tools are always accessed through an adapter interface. This means you could swap Cellpose for StarDist, or readlif for bioformats, without changing any domain code.
