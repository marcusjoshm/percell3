---
status: pending
priority: p2
issue_id: "007"
tags: [code-review, quality]
dependencies: []
---

# export_csv Accepts But Ignores cell_filters

## Problem Statement

`ExperimentStore.export_csv()` accepts `**cell_filters` in its signature but never forwards them to the underlying query. A caller writing `export_csv(path, condition="treated")` believes they are exporting a filtered subset of cells, but in reality they receive a CSV containing all cells in the experiment. This is a silent data correctness bug that could lead to incorrect downstream analysis.

## Findings

- `experiment_store.py:471-481` defines `export_csv(self, path, **cell_filters)`.
- The `**cell_filters` dictionary is accepted but never passed to `get_cells()`, `get_measurements()`, or any query function.
- The exported CSV always contains all cells regardless of what filters are passed.
- A researcher calling `export_csv("output.csv", condition="treated")` would unknowingly include control cells in their analysis, potentially invalidating results.
- No warning or error is raised when filters are passed.

## Proposed Solutions

### Option 1

Remove `**cell_filters` from the signature entirely. If filtering is not supported, the API should not pretend that it is. Callers who need filtered exports can filter the data after loading the CSV, or use `get_cells()` with proper filters and write the CSV themselves.

```python
# Before
def export_csv(self, path: str | Path, **cell_filters) -> None:

# After
def export_csv(self, path: str | Path) -> None:
```

### Option 2

Implement actual filtering by forwarding `**cell_filters` to the data retrieval step. This requires that the underlying query functions support the same filter keys. Given Finding 005, this should be done with explicit keyword arguments rather than `**kwargs` passthrough.

```python
def export_csv(
    self,
    path: str | Path,
    condition: str | None = None,
    region: str | None = None,
    is_valid: bool | None = None,
) -> None:
    cells = self.get_cells(condition=condition, region=region, is_valid=is_valid)
    # ... export filtered cells
```

## Technical Details

- File: `src/percell3/core/experiment_store.py`, lines 471-481
- This finding is related to Finding 005 (opaque `**kwargs` in `get_cell_count`). If Option 2 is chosen, the filter mechanism should be consistent across `get_cells`, `get_cell_count`, and `export_csv`.
- The fix is straightforward in either direction. Option 1 is safer if there is any doubt about filter semantics.

## Acceptance Criteria

- [ ] `export_csv` either does not accept filters or correctly applies them
- [ ] A test confirms that passing `condition="X"` to `export_csv` either raises an error (Option 1) or produces a CSV containing only cells from condition X (Option 2)
- [ ] No silent data loss or silent filter ignoring
- [ ] Docstring accurately documents the method's filtering behavior

## Work Log

### 2026-02-12 - Code Review Discovery

Identified during code review of `percell3.core`. The dead `**cell_filters` parameter is a correctness hazard because it silently discards user intent, potentially leading to incorrect scientific results.
