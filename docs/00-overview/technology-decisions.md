# PerCell 3 — Technology Decisions

## ADR-001: OME-Zarr over HDF5 for image storage
**Status**: Accepted
**Context**: Need compressed, structured image storage to replace individual TIFF files.
**Decision**: OME-Zarr (NGFF 0.4 spec) for all pixel data.
**Rationale**:
- Community standard — OME-NGFF is what the bioimaging field is converging on
- napari reads it natively (huge for visualization and debugging)
- Chunk-level access means you never load more data than needed
- Concurrent writes are natural (each chunk is a separate file)
- Future-proofs for cloud storage if a web version is ever needed
- The zarr library can also read HDF5 if backward compat is needed

## ADR-002: SQLite for metadata and measurements
**Status**: Accepted
**Context**: Need queryable storage for cell records, measurements, and config.
**Decision**: SQLite in WAL mode, one database per experiment.
**Rationale**:
- Zero installation, zero configuration, ships with Python
- Single file, easy to back up and share
- Fast enough for millions of cells (experiments will have thousands)
- WAL mode gives concurrent reads during writes
- Full SQL means complex queries are trivial
- CellProfiler proved this pattern works at scale

## ADR-003: New repository for PerCell 3
**Status**: Accepted
**Context**: PerCell 3 replaces the data model, processing backends, and CLI of PerCell 2.
**Decision**: Separate `percell3` repository. PerCell 2 remains stable.
**Rationale**: Different data model, different dependencies, different architecture. A branch implies merge; this is a new product that inherits domain knowledge, not code.

## ADR-004: readlif for LIF files (with GPL awareness)
**Status**: Accepted
**Context**: Need to read Leica LIF files. Options: readlif (GPL), bioformats2raw (GPL, Java), aicsimageio (BSD wrapper).
**Decision**: readlif as optional dependency, installed separately by user.
**Rationale**: Pure Python, no Java dependency. GPL handled by making it optional (`pip install percell3[lif]`).

## ADR-005: Click for CLI
**Status**: Accepted
**Context**: PerCell 2 has a custom interactive menu. Need composable commands.
**Decision**: Click command groups with Rich for output formatting.
**Rationale**: Industry standard, composable, built-in help, testable. Can add Textual TUI later.

## ADR-006: Plugin system via entry_points
**Status**: Accepted
**Context**: Need extensible analysis without modifying core code.
**Decision**: AnalysisPlugin ABC with discovery via setuptools entry_points and filesystem scanning.
**Rationale**: Standard Python pattern, allows both pip-installed and local script plugins.

## ADR-007: dask for lazy image access
**Status**: Accepted
**Context**: Images can be large (multi-GB). Loading entirely into memory is wasteful.
**Decision**: All image reads return dask arrays by default. Explicit `.read_image_numpy()` for in-memory.
**Rationale**: dask integrates naturally with zarr chunk-based storage. Process images chunk-by-chunk without custom streaming code. Users can `.compute()` when needed.

## ADR-008: pandas for measurement queries
**Status**: Accepted
**Context**: Measurement queries return tabular data. Need a standard format.
**Decision**: `get_cells()`, `get_measurements()`, `get_measurement_pivot()` return pandas DataFrames.
**Rationale**: Scientists already know pandas. Easy to export, plot, filter. Lightweight dependency that's already pulled in by most scientific Python stacks.
