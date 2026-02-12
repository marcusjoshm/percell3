# Architectural Decisions Log

## ADR-001: OME-Zarr over HDF5 for image storage
**Date**: 2026-02-12
**Status**: Accepted
**Context**: Need compressed, structured image storage to replace individual TIFF files.
**Decision**: OME-Zarr (NGFF 0.4 spec) for all pixel data.
**Rationale**: Community standard for bioimaging, napari reads it natively, chunk-level access, cloud-ready future, interop with Fiji/MoBIE. Zarr library can also read HDF5 if backward compat needed.

## ADR-002: Use SQLite for experiment metadata and measurements
**Date**: 2026-02-12
**Status**: Accepted
**Context**: Need queryable storage for cell records, measurements, and config.
**Decision**: SQLite in WAL mode, one database per experiment.
**Rationale**: Zero-config, ships with Python, single portable file, fast enough for millions of cells, CellProfiler proved this pattern at scale.

## ADR-003: New repository for PerCell 3
**Date**: 2026-02-12
**Status**: Accepted
**Context**: PerCell 3 replaces the data model, processing backends, and CLI of PerCell 2.
**Decision**: Separate `percell3` repository. PerCell 2 remains as stable tool.
**Rationale**: Different data model, different dependencies, different architecture. A branch implies merge; this is a new product.

## ADR-004: readlif for LIF file reading (with GPL awareness)
**Date**: 2026-02-12
**Status**: Accepted
**Context**: Need to read Leica LIF files. Options: readlif (GPL), bioformats2raw (GPL, Java), aicsimageio (BSD wrapper, readlif as optional GPL dep).
**Decision**: readlif as optional dependency, installed separately by user.
**Rationale**: Pure Python, no Java dependency. GPL license handled by making it optional (same pattern as aicsimageio).

## ADR-005: Click for CLI over custom menu system
**Date**: 2026-02-12
**Status**: Accepted
**Context**: PerCell 2 has a custom interactive menu. Need something more composable.
**Decision**: Click command groups with Rich for output formatting.
**Rationale**: Industry standard, composable, built-in help, testable, can add Textual TUI later.

## ADR-006: Plugin system via entry_points + directory scanning
**Date**: 2026-02-12
**Status**: Accepted
**Context**: Need extensible analysis without modifying core code.
**Decision**: AnalysisPlugin ABC with discovery via setuptools entry_points and filesystem scanning.
**Rationale**: Standard Python pattern, allows both pip-installed plugins and local script plugins.
