# CLAUDE.md — PerCell 3

## Project Overview
PerCell 3 is a single-cell microscopy analysis platform built on OME-Zarr and SQLite.
It replaces PerCell 2's filesystem-based data model with a proper experiment database.

## Architecture Principles
- **ExperimentStore is the center of everything.** All modules interact through it.
- **OME-Zarr for pixels, SQLite for metadata and measurements.** Never store experiment state in directory names or filenames.
- **Hexagonal architecture.** Domain logic has no dependencies on frameworks. External tools (Cellpose, ImageJ, readlif) are accessed through adapter interfaces.
- **Channels are first-class citizens.** Any operation can target any channel. Segmentation channel != measurement channel.
- **Plugins over hardcoded stages.** Every analysis routine should be implementable as a plugin that reads from ExperimentStore and writes results back.

## Technology Stack
- Python 3.10+
- zarr + ome-zarr for image storage (OME-NGFF 0.4 spec)
- SQLite via sqlite3 stdlib for experiment database
- dask.array for lazy/chunked image access
- readlif for Leica LIF file reading (optional, GPL)
- tifffile for TIFF reading/writing
- cellpose for segmentation
- scikit-image + scipy for image processing
- click for CLI
- rich for terminal output
- pytest for testing

## Code Conventions
- Type hints on all public functions
- Docstrings in Google style
- dataclasses for value objects, no NamedTuples
- Abstract base classes for ports/interfaces
- No global state — everything through ExperimentStore or dependency injection
- Tests alongside source: tests/test_<module>/ mirrors src/percell3/<module>/

## Module Structure
```
percell3/
├── src/percell3/
│   ├── __init__.py
│   ├── core/           # Module 1: ExperimentStore, schema, Zarr I/O
│   │   ├── experiment_store.py   # Central interface — SQLite + Zarr R/W, export
│   │   ├── schema.py             # SQLite DDL (schema 4.0.0)
│   │   ├── models.py             # Frozen dataclasses for domain objects
│   │   ├── queries.py            # Reusable SQL query builders
│   │   ├── zarr_io.py            # Zarr read/write for images, labels, masks
│   │   ├── constants.py          # Metric names, scopes, batch defaults
│   │   ├── exceptions.py         # ExperimentError hierarchy
│   │   └── tiff_export.py        # export_fov_as_tiff()
│   ├── io/             # Module 2: Format readers (LIF, TIFF, CZI)
│   │   ├── engine.py             # ImportEngine
│   │   ├── scanner.py            # FileScanner — discovers TIFF/LIF/CZI
│   │   ├── tiff.py               # TIFF reader
│   │   ├── transforms.py         # Z-projection (MIP, mean, sum)
│   │   └── percell_import.py     # Cross-project FOV import with ID remapping
│   ├── segment/        # Module 3: Segmentation engine
│   │   ├── _engine.py            # SegmentationEngine
│   │   ├── cellpose_adapter.py   # Cellpose integration
│   │   ├── label_processor.py    # Cell extraction, edge/small-cell filtering
│   │   ├── roi_import.py         # Import label images and _seg.npy files
│   │   ├── imagej_roi_reader.py  # Read ImageJ ROI .zip files
│   │   └── viewer/               # Napari widgets
│   ├── measure/        # Module 4: Measurement engine
│   ├── plugins/        # Module 5: Plugin system + built-in plugins
│   ├── workflow/        # Module 6: DAG-based workflow engine
│   └── cli/            # Module 7: Click CLI + interactive menu
├── tests/
├── docs/               # Module specs, planning docs, subagent instructions
├── pyproject.toml
└── CLAUDE.md
```

## Plugins

Six built-in plugins discovered automatically by `PluginRegistry`:

| Plugin | Type | Description |
|---|---|---|
| `local_bg_subtraction` | Analysis | Per-particle local background subtraction with Gaussian peak detection |
| `threshold_bg_subtraction` | Analysis | Per-threshold-layer histogram-based background subtraction, creates derived FOVs |
| `split_halo_condensate_analysis` | Analysis | BiFC split-Halo sensor: granule + dilute phase measurements |
| `image_calculator` | Analysis | Pixel-level arithmetic on channels (add, subtract, multiply, etc.) |
| `nan_zero` | Analysis | Replace zero-valued pixels with NaN, creates derived FOVs with NaN-safe measurements |
| `surface_plot_3d` | Visualization | 3D surface plot visualization in napari |

## Workflows

Two built-in workflows available from the interactive menu:

- **Particle analysis** — Standard pipeline: segment cells, measure channels, apply grouped intensity thresholds, export CSV.
- **Decapping sensor** — 11-step automated pipeline for BiFC split-Halo decapping assays: iterative thresholding across 3 rounds, split-halo condensate analysis (keep dilute, discard condensed), threshold-based background subtraction, and filtered CSV export with threshold pair deduplication.

## Subagent Coordination
Each module (01-core through 07-cli) has its own CLAUDE.md in docs/.
Subagents should ONLY read their own module's spec + the 00-overview docs.
All modules depend on 01-core. Modules 02-05 can be built in parallel after 01-core.
Module 06 integrates 02-05. Module 07 wraps everything.

## Running Tests
```bash
pytest tests/ -v
pytest tests/test_core/ -v           # Test single module
```

## Building
```bash
pip install -e ".[dev]"
```

## Key Domain Terms
- **Experiment**: One .percell directory containing all data for an analysis
- **Condition**: Experimental condition (e.g., "control", "treated")
- **FOV**: Field of view / technical replicate (called "Region" in some older docs)
- **Channel**: An imaging channel (DAPI, GFP, RFP, etc.)
- **Cell**: A segmented object with a unique ID, bbox, and measurements
- **Label image**: Integer-coded image where pixel value = cell ID
- **Measurement**: A scalar value for one cell x one channel x one scope (whole_cell, mask_inside, mask_outside)
- **Segmentation**: A named global segmentation entity, assigned to FOVs via fov_config (not per-FOV)
- **Threshold**: A named intensity threshold applied to a channel, creating binary masks (inside/outside)
- **Particle**: A connected component within a threshold mask, with morphometric measurements
- **Plugin**: A Python class implementing `AnalysisPlugin` or `VisualizationPlugin` ABC
- **Derived FOV**: A new FOV created by a plugin (e.g., BG-subtracted or NaN-zeroed), preserving lineage to the original
- **FOV Config**: Per-FOV assignment of segmentations and thresholds (the layer-based configuration model)

## Architecture Notes

- **Layer-based architecture (schema 4.0.0):** Segmentations and thresholds are global named entities, assigned to FOVs via `fov_config`. Measurements are automatic side effects of config changes (via `on_config_changed()`).
- **NaN-safe metrics:** All 7 measurement metrics (mean, max, min, integrated, std, median, area) use `np.nanmean`/`np.nanmax`/etc. to handle NaN pixels from derived FOVs.
- **Derived FOV four-step contract:** Any plugin creating a derived FOV must: (1) create the FOV and write channels to Zarr, (2) copy `fov_config` entries from the source FOV, (3) duplicate cells, (4) run measurements on the new FOV.
