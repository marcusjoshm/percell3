# CLAUDE.md — Module 1: Core (percell3.core)

## Your Task
Build the core data layer for PerCell 3. This module defines the SQLite schema,
the ExperimentStore class, and the OME-Zarr read/write utilities. Everything
else in PerCell 3 depends on this module.

## Read First (in order)
1. `../00-overview/architecture.md` — Full system architecture
2. `./spec.md` — Detailed specification for this module
3. `./schema.sql` — The SQLite schema you must implement
4. `./zarr-layout.md` — The OME-Zarr directory structure

## Output Location
- Source code: `src/percell3/core/`
- Tests: `tests/test_core/`

## Files to Create
```
src/percell3/core/
├── __init__.py              # Public API exports
├── experiment_store.py      # ExperimentStore class (central object)
├── schema.py                # SQLite schema creation and migration
├── models.py                # Dataclasses: ChannelConfig, CellRecord, etc.
├── zarr_io.py               # OME-Zarr read/write utilities
├── queries.py               # Named SQL queries as functions
└── exceptions.py            # ExperimentError, ChannelNotFoundError, etc.
```

## Acceptance Criteria
1. `ExperimentStore.create(path)` creates a .percell directory with experiment.db and images.zarr
2. `ExperimentStore.open(path)` opens an existing .percell directory
3. Can add channels, conditions, timepoints, regions to the database
4. Can write a numpy array as an OME-Zarr group with proper NGFF 0.4 metadata
5. Can read back any channel/region as a dask.array
6. Can write cell records to SQLite and query them with filters
7. Can write measurements and query them across channels
8. All operations are idempotent where possible (re-importing same data = no duplicates)
9. SQLite is in WAL mode for concurrent read safety

## Dependencies You Can Use
zarr, ome-zarr, numpy, dask, pandas, sqlite3 (stdlib), dataclasses (stdlib)

## Dependencies You Must NOT Use
cellpose, readlif, click, rich, scikit-image — those belong to other modules.

## Key Constraints
- ExperimentStore must be the ONLY way to read/write the .percell directory
- All SQL queries go through ExperimentStore methods, never raw SQL in other modules
- OME-Zarr writes must conform to NGFF 0.4 spec
- All image arrays accessed via dask by default (lazy loading)
- Thread-safe SQLite access (use WAL mode, proper connection handling)
- The .percell directory must be self-contained and portable (copy it = copy the experiment)
