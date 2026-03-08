---
title: "feat: Add FOV filter to CSV export"
type: feat
date: 2026-03-04
brainstorm: docs/brainstorms/2026-03-04-csv-export-fov-filter-brainstorm.md
---

# feat: Add FOV Filter to CSV Export

## Overview

Add a FOV selection step to all three CSV export paths (wide-format, particle, prism) in the DATA menu. Currently all exports include every FOV unconditionally. Users need to select a subset of FOVs.

## Proposed Solution

Add `fov_ids: list[int] | None = None` parameter to the three export methods (`export_csv`, `export_particles_csv`, `export_prism_csv`) and their dependencies. `None` = all FOVs (backward compatible). In the CLI handler, add a FOV selection step using the established `_select_fovs_from_table` pattern.

## Implementation Plan

### Phase 1: Add `fov_ids` to core export methods

**File:** `src/percell3/core/experiment_store.py`

- [x] Add `fov_ids: list[int] | None = None` param to `get_measurement_pivot()` — resolve to `cell_ids` via `get_cells()` filtered by FOV, pass to `get_measurements(cell_ids=...)`
- [x] Add `fov_ids: list[int] | None = None` param to `export_csv()` — pass through to `get_measurement_pivot()`
- [x] Add `fov_ids: list[int] | None = None` param to `export_prism_csv()` — filter `get_measurements()` call and `get_cells()` call
- [x] Add `fov_ids: list[int] | None = None` param to `export_particles_csv()` — filter particle DataFrame after query by `fov_id` column

Threading pattern for cell measurements:
```python
# In get_measurement_pivot():
def get_measurement_pivot(self, ..., fov_ids=None):
    cell_ids = None
    if fov_ids is not None:
        cells_df = self.get_cells(is_valid=True)
        cell_ids = cells_df[cells_df["fov_id"].isin(fov_ids)]["id"].tolist()
    df = self.get_measurements(cell_ids=cell_ids, ...)
```

Threading pattern for particles:
```python
# In export_particles_csv():
rows = queries.select_particles_with_context(self._conn)
if fov_ids is not None:
    rows = [r for r in rows if r["fov_id"] in set(fov_ids)]
```

### Phase 2: Add FOV selection to CLI handler

**File:** `src/percell3/cli/menu.py` — `_export_csv()`

- [x] Add FOV selection step after format selection (Step 2), before path prompt
- [x] Use `_select_fovs_from_table` pattern (same as segment, measure, threshold handlers)
- [x] Pass `fov_ids` to `export_csv()`, `export_particles_csv()`, `export_prism_csv()`
- [x] Show selected FOV count in confirmation summary
- [x] Blank/all selection = `None` (all FOVs, current behavior preserved)

New interactive flow:
```
Step 1: Format selection (wide vs prism) — existing
Step 2: FOV selection — NEW
Step 3: Path prompt — existing
Step 4+: Channel/metric/scope filters — existing
```

Also update `_export_prism()` handler to include FOV selection.

### Phase 3: Tests

**File:** `tests/test_cli/test_export.py`

- [ ] Add test: export with FOV subset produces only rows from selected FOVs
- [ ] Add test: export with all FOVs (None) matches current behavior
- [ ] Add test: particle export with FOV filter
- [ ] Add test: prism export with FOV filter

## Acceptance Criteria

- [ ] `export_csv(fov_ids=[...])` only exports cells from specified FOVs
- [ ] `export_particles_csv(fov_ids=[...])` only exports particles from specified FOVs
- [ ] `export_prism_csv(fov_ids=[...])` only exports cells from specified FOVs
- [ ] `fov_ids=None` (default) exports all FOVs — backward compatible
- [ ] CLI prompts user to select FOVs using `_select_fovs_from_table`
- [ ] Blank/all selection in CLI passes `None` (no filter)
- [ ] FOV selection appears in both wide-format and prism export flows

## References

- FOV selection pattern: `src/percell3/cli/menu.py:1563` (`_select_fovs_from_table`)
- Export handler: `src/percell3/cli/menu.py:3285` (`_export_csv`)
- Prism handler: `src/percell3/cli/menu.py:3422` (`_export_prism`)
- `get_measurements`: `src/percell3/core/experiment_store.py:659` (already has `cell_ids` param)
- `select_particles_with_context`: `src/percell3/core/queries.py:872` (already has `fov_id` param)

### Learnings Applied
- `docs/solutions/ui-bugs/particle-export-missing-metric-options.md` — derive filter options dynamically from store, never hardcode
- `docs/solutions/architecture-decisions/cli-module-code-review-findings.md` — menu handler patterns
