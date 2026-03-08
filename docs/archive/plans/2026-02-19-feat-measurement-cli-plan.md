---
title: "feat: Measurement CLI with whole-cell and mask-based modes"
type: feat
date: 2026-02-19
brainstorm: docs/brainstorms/2026-02-19-measurement-cli-brainstorm.md
---

# Measurement CLI — Whole-Cell + Mask-Based Modes

## Overview

Wire the existing measurement backend (`Measurer`, `MetricRegistry`, `BatchMeasurer`) into CLI menu item 5, add a `scope` column to distinguish whole-cell from mask-based measurements, and auto-trigger whole-cell measurements after segmentation.

## Problem Statement

Menu item 6 "Apply threshold" requires per-cell measurements for grouping, but menu item 5 "Measure channels" is disabled. The measurement backend is fully built and tested — only CLI wiring and a schema extension are needed.

## Architecture

```
                    Menu Item 5                     Menu Item 3
                 _measure_channels              _segment_cells
                    /          \                       |
               whole-cell    mask-based          auto-measure
                    |            |                     |
              BatchMeasurer   Measurer          BatchMeasurer
              .measure_       .measure_          .measure_
              experiment()    fov_masked()        experiment()
                    \          /                       |
                  store.add_measurements()    store.add_measurements()
                          |                           |
                  measurements table (with scope column)
```

## Data Model Changes

### Schema: `measurements` table

```sql
-- Add two columns (ALTER TABLE migration)
ALTER TABLE measurements ADD COLUMN scope TEXT NOT NULL DEFAULT 'whole_cell';
ALTER TABLE measurements ADD COLUMN threshold_run_id INTEGER REFERENCES threshold_runs(id);

-- Drop old unique constraint and create new one
-- (SQLite doesn't support DROP CONSTRAINT, so recreate via temp table)
-- New unique: UNIQUE(cell_id, channel_id, metric, scope)
```

**Scope values**: `whole_cell` (default), `mask_inside`, `mask_outside`
**CHECK constraint**: `scope IN ('whole_cell', 'mask_inside', 'mask_outside')`

The `threshold_run_id` is informational (which threshold produced the mask) — not part of the unique constraint. Re-running mask measurements for the same scope overwrites silently.

### MeasurementRecord dataclass

```python
@dataclass(frozen=True)
class MeasurementRecord:
    cell_id: int
    channel_id: int
    metric: str
    value: float
    scope: str = "whole_cell"
    threshold_run_id: int | None = None
```

Defaults ensure backward compatibility — all existing callers continue working.

### Schema version bump: 3.2.0 → 3.3.0

Migration for existing experiments:
1. `ALTER TABLE measurements ADD COLUMN scope TEXT NOT NULL DEFAULT 'whole_cell'`
2. `ALTER TABLE measurements ADD COLUMN threshold_run_id INTEGER`
3. Recreate table with new unique constraint (SQLite requires temp table swap)
4. Update `schema_version` row

---

## Implementation Phases

### Phase 1: Data Layer — scope column + migration

#### Files to modify

| File | Changes |
|------|---------|
| `src/percell3/core/schema.py` | Update `CREATE TABLE measurements` DDL, add CHECK constraint, update unique constraint, bump EXPECTED_VERSION to 3.3.0, add migration function |
| `src/percell3/core/models.py` | Add `scope` and `threshold_run_id` to `MeasurementRecord` |
| `src/percell3/core/queries.py` | Update `insert_measurements` and `select_measurements` to include scope/threshold_run_id columns |
| `src/percell3/core/experiment_store.py` | Update `add_measurements`, `get_measurements`, `get_measurement_pivot` to pass through scope |

#### Tasks

- [ ] Add `scope TEXT NOT NULL DEFAULT 'whole_cell'` and `threshold_run_id INTEGER` to measurements DDL in schema.py
- [ ] Add `CHECK(scope IN ('whole_cell', 'mask_inside', 'mask_outside'))` constraint
- [ ] Update unique constraint to `UNIQUE(cell_id, channel_id, metric, scope)`
- [ ] Add migration function `_migrate_3_2_to_3_3()` using temp table swap pattern
- [ ] Bump `EXPECTED_VERSION` to `"3.3.0"`, wire migration in `open_database()`
- [ ] Add `scope: str = "whole_cell"` and `threshold_run_id: int | None = None` to `MeasurementRecord`
- [ ] Update `insert_measurements()` SQL to include scope and threshold_run_id columns
- [ ] Update `select_measurements()` to include scope in return dict and add optional scope filter
- [ ] Update `get_measurement_pivot()` to incorporate scope into column names when non-whole_cell rows exist
- [ ] Write tests for schema migration (old DB → new DB)
- [ ] Write tests for insert/select with scope
- [ ] Run full test suite — all existing tests must pass

### Phase 2: Masked Measurer — `measure_fov_masked()`

#### Files to modify

| File | Changes |
|------|---------|
| `src/percell3/measure/measurer.py` | Add `measure_fov_masked()` method |
| `tests/test_measure/test_measurer.py` | Tests for masked measurement |

#### Tasks

- [ ] Add `measure_fov_masked()` to `Measurer` class
- [ ] Signature: `measure_fov_masked(store, fov, condition, channels, threshold_channel, threshold_run_id, scopes, metrics, bio_rep, timepoint) -> int`
- [ ] `scopes` parameter: `list[str]` subset of `["mask_inside", "mask_outside"]`
- [ ] For each cell: crop threshold mask to bbox, compute `inside_mask = cell_mask & thresh_crop` and `outside_mask = cell_mask & ~thresh_crop`
- [ ] Cells with 0 pixels in the scoped mask: write `value=0.0` for all metrics (not skip — keeps data complete)
- [ ] Follow existing bbox-optimized per-cell pattern from `_measure_cells_on_channel`
- [ ] Read threshold mask once per FOV via `store.read_mask(fov, condition, threshold_channel)`
- [ ] Write tests: basic inside/outside, both scopes, 0-pixel cells, correct scope values in records
- [ ] Run test suite

### Phase 3: CLI Handler — `_measure_channels()`

#### Files to modify

| File | Changes |
|------|---------|
| `src/percell3/cli/menu.py` | Add `_measure_channels()`, enable menu item 5 |

#### Tasks

- [ ] Enable menu item 5: `MenuItem("5", "Measure channels", _measure_channels, enabled=True)`
- [ ] Implement `_measure_channels(state)` with mode selection:
  ```
  Measurement mode:
    [1] Whole cell (all channels, all metrics)
    [2] Inside threshold mask
    [3] Outside threshold mask
    [4] Both inside + outside mask
  ```
- [ ] **Whole-cell mode flow**:
  1. Guard: require channels, FOVs, cells
  2. Show FOV table with measurement status
  3. FOV selection (default: all)
  4. Confirmation summary
  5. Run `BatchMeasurer.measure_experiment(store, progress_callback=...)`
  6. Print result summary
- [ ] **Mask-based mode flow**:
  1. Guard: require threshold runs to exist
  2. Show available threshold channels (from threshold_runs)
  3. User selects threshold channel
  4. User selects measurement channels (default: all)
  5. Show FOV table (filtered to FOVs with mask for selected threshold channel)
  6. FOV selection
  7. Confirmation summary
  8. Loop FOVs: call `Measurer.measure_fov_masked()` with progress
  9. Print result summary
- [ ] Handle navigation: 'b' at mode selection returns to main menu
- [ ] Run CLI tests

### Phase 4: Auto-Measure After Segmentation

#### Files to modify

| File | Changes |
|------|---------|
| `src/percell3/cli/menu.py` | Add auto-measure call at end of `_segment_cells()` |

#### Tasks

- [ ] After segmentation results print, add auto-measure block:
  ```python
  if result.cell_count > 0:
      console.print("\n[bold]Auto-measuring all channels...[/bold]")
      # Run BatchMeasurer on just-segmented FOVs
  ```
- [ ] Show progress bar during auto-measure (consistent with segmentation)
- [ ] Fire-and-forget on error: catch exceptions, print warning, don't fail segmentation
- [ ] Print brief summary: `"Measured {n} metrics x {c} channels for {cells} cells"`
- [ ] Only measure the FOVs that were just segmented (not all FOVs)
- [ ] Run test suite

### Phase 5: Export Integration

#### Files to modify

| File | Changes |
|------|---------|
| `src/percell3/core/experiment_store.py` | Update `get_measurement_pivot()` for scope |
| `src/percell3/cli/menu.py` | Add scope filter to export flow |

#### Tasks

- [ ] Update `get_measurement_pivot()`: when mask-scoped rows exist, append scope to column name (e.g., `GFP_mean_intensity_inside`)
- [ ] Whole-cell columns keep simple names (no `_whole_cell` suffix) for backward compatibility
- [ ] Add optional `scope` parameter to `get_measurements()` and `get_measurement_pivot()`
- [ ] Write tests for pivot with mixed scopes
- [ ] Run full test suite — all tests must pass

---

## Acceptance Criteria

### Functional

- [ ] Menu item 5 "Measure channels" works end-to-end for whole-cell mode
- [ ] Menu item 5 works for mask-based mode (inside, outside, both)
- [ ] Auto-measure fires after segmentation with progress bar
- [ ] Measurements table has `scope` and `threshold_run_id` columns
- [ ] `INSERT OR REPLACE` correctly overwrites by `(cell_id, channel_id, metric, scope)`
- [ ] Existing experiments migrate from 3.2.0 to 3.3.0 on open
- [ ] CSV export includes scope-aware column names
- [ ] Thresholding (menu item 6) works after running measurements

### Architecture

- [ ] No imports of `queries`, `schema`, or `zarr_io` outside of `core/`
- [ ] `MeasurementRecord` backward compatible (defaults for new fields)
- [ ] `Measurer.measure_fov_masked()` follows bbox-optimized per-cell pattern
- [ ] Auto-measure uses fire-and-forget error handling

### Testing

- [ ] Schema migration tests (old DB → new DB round-trip)
- [ ] Measurement insert/select with scope tests
- [ ] Masked measurer tests (inside, outside, both, 0-pixel cells)
- [ ] CLI handler tests (mocked)
- [ ] Export pivot with mixed scopes
- [ ] All existing tests still pass

---

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Unique constraint | `(cell_id, channel_id, metric, scope)` | threshold_run_id is informational, not uniqueness key |
| threshold_run_id NULL handling | NULL for whole_cell rows, set for mask rows | No sentinel value needed since it's not in unique constraint |
| 0-pixel cells in mask | Write value=0.0 | Keeps data complete; every cell has every metric |
| Auto-measure scope | Only newly segmented FOVs | Avoids re-measuring unchanged FOVs |
| Auto-measure error handling | Fire-and-forget with printed warning | Segmentation success is primary, measurement is secondary |
| Export format | Wide: `GFP_mean_intensity`, `GFP_mean_intensity_inside` | Whole-cell gets clean names; mask scopes get suffix |
| BatchMeasurer for masked | Not extended; use Measurer directly in loop | Simpler; same pattern as _apply_threshold |
| Threshold run picker | Group by channel, show most recent per channel | Avoids overwhelming list of runs |

## References

### Internal

- `src/percell3/measure/measurer.py` — existing Measurer with `measure_fov()` and `_measure_cells_on_channel()`
- `src/percell3/measure/batch.py` — BatchMeasurer with `measure_experiment()`
- `src/percell3/measure/metrics.py` — MetricRegistry with 7 built-in metrics
- `src/percell3/cli/menu.py:700` — `_segment_cells()` handler pattern
- `src/percell3/cli/menu.py:856` — `_apply_threshold()` handler pattern
- `src/percell3/core/schema.py:95` — current measurements table DDL
- `src/percell3/core/queries.py:560` — current `insert_measurements()` query
- `docs/solutions/design-gaps/measurement-cli-and-threshold-prerequisites.md` — gap documentation

### Brainstorm

- `docs/brainstorms/2026-02-19-measurement-cli-brainstorm.md` — all design decisions
