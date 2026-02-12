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
│   ├── io/             # Module 2: Format readers (LIF, TIFF, CZI)
│   ├── segment/        # Module 3: Segmentation engine
│   ├── measure/        # Module 4: Measurement engine
│   ├── plugins/        # Module 5: Plugin system + built-in plugins
│   ├── workflow/        # Module 6: DAG-based workflow engine
│   └── cli/            # Module 7: Click CLI
├── tests/
├── docs/               # Module specs, planning docs, subagent instructions
├── pyproject.toml
└── CLAUDE.md
```

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
- **Region**: A single field of view / technical replicate
- **Channel**: An imaging channel (DAPI, GFP, RFP, etc.)
- **Cell**: A segmented object with a unique ID, bbox, and measurements
- **Label image**: Integer-coded image where pixel value = cell ID
- **Measurement**: A scalar value for one cell x one channel
- **Plugin**: A Python class that reads from ExperimentStore and writes measurements back
