---
review_agents: [kieran-python-reviewer, code-simplicity-reviewer, security-sentinel, performance-oracle]
plan_review_agents: [kieran-python-reviewer, code-simplicity-reviewer]
---

# Review Context

PerCell 3 is a single-cell microscopy analysis platform. The core module (percell3.core) is the foundation:
- ExperimentStore wraps a .percell directory with SQLite + OME-Zarr
- All SQL goes through queries.py (standalone functions taking Connection)
- Zarr I/O through zarr_io.py (standalone functions)
- NGFF 0.4 metadata compliance required for image storage
- Python 3.10+ with type hints, Google-style docstrings, dataclasses
- No global state — everything through ExperimentStore or dependency injection
