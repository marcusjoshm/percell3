---
title: "Remove private _conn access from segment module — hexagonal architecture fix"
date: 2026-02-16
category: architecture-decisions
tags: [hexagonal-architecture, encapsulation, private-api, code-review, segment]
modules: [core, segment]
severity: p1
symptoms:
  - "segment._engine directly accessed store._conn for database updates"
  - "roi_import.py accessed store._conn in two locations (import_labels, import_cellpose_seg)"
  - "4/4 code review agents flagged during segment module review (commit 609ed2d)"
root_cause: "Segment module bypassed ExperimentStore public API by accessing private _conn attribute to call queries.update_segmentation_run_cell_count() directly"
resolution_time: 30min
---

# Segment Module Private API Encapsulation Fix

## Problem

The segment module violated PerCell 3's hexagonal architecture principle by directly accessing `store._conn` (private SQLite connection) from ExperimentStore in **3 locations**:

```python
# src/percell3/segment/_engine.py:152
from percell3.core import queries
queries.update_segmentation_run_cell_count(store._conn, run_id, total_cells)
```

```python
# src/percell3/segment/roi_import.py:97
queries.update_segmentation_run_cell_count(store._conn, run_id, len(cells))
```

```python
# src/percell3/segment/roi_import.py:192
queries.update_segmentation_run_cell_count(store._conn, run_id, len(cells))
```

This violates the CLAUDE.md principle: **"ExperimentStore is the center of everything. All modules interact through it."**

By importing `queries` and accessing `_conn`, the segment module was:
1. Bypassing ExperimentStore's public API
2. Coupling to internal SQLite implementation details
3. Breaking the hexagonal architecture boundary

## Investigation

Discovered during a comprehensive code review of the `feat/segment-module` branch (commit `609ed2d`). All 4 review agents (Python, security, performance, agent-native) independently flagged this as a P1 issue — unanimous finding.

Detection was straightforward: searching for `store._conn` usage outside the core module.

## Root Cause

The initial `SegmentationEngine` implementation needed to update cell counts after processing all regions. Rather than adding a public method to ExperimentStore, the developer directly imported the `queries` module and called the underlying function with the private connection. The pattern was likely copied from internal core module usage.

## Solution

**Commit `f4db399`** — three-part fix:

### 1. Add public method to ExperimentStore

```python
# src/percell3/core/experiment_store.py
def update_segmentation_run_cell_count(
    self, run_id: int, cell_count: int
) -> None:
    """Update the cell count for a segmentation run."""
    queries.update_segmentation_run_cell_count(self._conn, run_id, cell_count)
```

### 2. Update all 3 call sites

```python
# Before (all 3 locations):
queries.update_segmentation_run_cell_count(store._conn, run_id, total_cells)

# After:
store.update_segmentation_run_cell_count(run_id, total_cells)
```

### 3. Remove dead imports

- `from percell3.core import queries` removed from `_engine.py` and `roi_import.py`
- `import json` removed from `_engine.py` (unrelated dead import)

## Impact

- **Architecture compliance**: Segment module uses only ExperimentStore's public API
- **Reduced coupling**: No dependency on `queries` module or SQLite internals from outside core
- **Maintainability**: Future refactoring of queries or schema won't require segment module changes
- **Testability**: Segment module can be tested with a mock ExperimentStore

## Prevention Strategies

### 1. Grep for violations before merging

```bash
# Detect private attribute access from outside core
grep -r 'store\._[a-z]' src/percell3/{io,segment,measure,plugins,workflow,cli}/ \
  --include="*.py" | grep -v "self._"

# Detect internal module imports
grep -r 'from percell3.core import queries\|from percell3.core import schema' \
  src/percell3/{io,segment,measure,plugins,workflow,cli}/ --include="*.py"
```

### 2. Architecture boundary test

```python
# tests/test_architecture/test_hexagonal_boundary.py
import ast
from pathlib import Path

@pytest.mark.parametrize("module_dir", [
    "src/percell3/segment",
    "src/percell3/measure",
    "src/percell3/plugins",
    "src/percell3/workflow",
])
def test_no_private_store_access(module_dir):
    """No module accesses store._conn or other private attributes."""
    for py_file in Path(module_dir).glob("**/*.py"):
        source = py_file.read_text()
        tree = ast.parse(source, filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                if (isinstance(node.value, ast.Name)
                    and node.value.id == "store"
                    and node.attr.startswith("_")):
                    raise AssertionError(
                        f"{py_file}:{node.lineno}: store.{node.attr} — use public API"
                    )
```

### 3. API completeness checklist

Before starting a new module, verify ExperimentStore exposes all required operations:
- List the store operations your module needs from the spec
- Check each exists as a public method (no `_` prefix)
- If missing, add the method to ExperimentStore first

### 4. Module import rule

Modules outside `core/` should only import:
- `from percell3.core import ExperimentStore`
- `from percell3.core.exceptions import ...`
- Dataclasses and type definitions

Never import `queries`, `schema`, or `zarr_io` from outside core.

## Additional Context

This fix was part of commit `f4db399` which addressed 3 P1 findings from the segment module review:

| ID | Priority | Finding | Status |
|---|---|---|---|
| 033 | P1 | Cellpose 4.0 API break | Fixed |
| 034 | P1 | Private `store._conn` access (this document) | Fixed |
| 035 | P1 | `np.load(allow_pickle=True)` security warning | Fixed |

## Cross-References

- [Todo 034: Private _conn access](../../../todos/034-complete-p1-private-conn-access.md)
- [Cellpose 4.0 API Breaking Change](../integration-issues/cellpose-4-0-api-breaking-change.md) — sibling P1 fix with full review findings table
- [Architecture Overview](../../00-overview/architecture.md) — hexagonal architecture principles
- [Module 3 Spec](../../03-segment/spec.md) — segment module design
- [CLI Module Code Review Findings](cli-module-code-review-findings.md) — related architectural review
