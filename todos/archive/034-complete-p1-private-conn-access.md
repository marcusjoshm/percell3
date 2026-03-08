---
status: complete
priority: p1
issue_id: "034"
tags: [code-review, segment, architecture, encapsulation]
dependencies: []
---

# Segment Module Accesses Private `store._conn` — Breaks Hexagonal Architecture

## Problem Statement

The segment module reaches into `ExperimentStore._conn` (private attribute) to call `queries.update_segmentation_run_cell_count()` directly. This violates the hexagonal architecture principle that "all modules interact through ExperimentStore" and creates tight coupling to SQLite internals.

Found by 4 out of 4 review agents (Python, security, performance, agent-native).

## Findings

3 locations access `store._conn`:
1. `src/percell3/segment/_engine.py:152` — `queries.update_segmentation_run_cell_count(store._conn, run_id, total_cells)`
2. `src/percell3/segment/roi_import.py:97` — same pattern
3. `src/percell3/segment/roi_import.py:192` — same pattern

## Proposed Solutions

### Option 1 (Recommended): Add public method to ExperimentStore

```python
# In ExperimentStore:
def update_segmentation_run_cell_count(self, run_id: int, cell_count: int) -> None:
    queries.update_segmentation_run_cell_count(self._conn, run_id, cell_count)
```

Then replace all 3 call sites:
```python
store.update_segmentation_run_cell_count(run_id, total_cells)
```

- Pros: Clean boundary, consistent with existing API pattern
- Cons: None
- Effort: Small
- Risk: Low

## Acceptance Criteria

- [x] No references to `store._conn` in segment module
- [x] New public method on ExperimentStore
- [x] All tests pass (360/360)

## Work Log

### 2026-02-16 — Code Review Discovery
Identified by all review agents. Unanimous finding.

### 2026-02-16 — Fixed
Added `update_segmentation_run_cell_count()` to `ExperimentStore`. Updated all 3 call sites in `_engine.py:150` and `roi_import.py:95,189`. Removed unused `from percell3.core import queries` imports from both files. Also removed unused `import json` from `_engine.py`.
