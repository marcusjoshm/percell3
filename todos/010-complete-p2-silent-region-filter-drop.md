---
status: pending
priority: p2
issue_id: "010"
tags: [code-review, quality]
dependencies: []
---

# Silent Region Filter Drop

## Problem Statement

`ExperimentStore.get_cells(region="r1")` called without a `condition` argument silently ignores the `region` filter and returns ALL cells in the experiment instead of only cells from region "r1". This is a data correctness bug: the caller explicitly requested a subset of cells but receives the full dataset with no warning. Additionally, there is a redundant condition ID re-resolution on line 295 that indicates the filtering logic was not carefully reviewed.

## Findings

- When `get_cells(region="r1")` is called without `condition`, the code path that applies the region filter is never reached because region lookup requires a condition ID.
- Instead of raising an error explaining that region filtering requires a condition, the method silently falls through to the unfiltered query.
- The caller receives all cells, believing they received only cells from "r1".
- Line 295 contains a redundant re-resolution of `cond_id` that was already resolved earlier in the function, suggesting the filtering logic was patched incrementally without a holistic review.
- This is particularly dangerous in scientific analysis where operating on the wrong subset of cells can invalidate experimental conclusions.

## Proposed Solutions

### Option 1

Raise a `ValueError` when `region` is provided without `condition`, making the requirement explicit:

```python
def get_cells(
    self,
    condition: str | None = None,
    region: str | None = None,
    region_id: int | None = None,
    is_valid: bool | None = None,
) -> list[CellInfo]:
    if region is not None and condition is None:
        raise ValueError(
            "A 'condition' must be provided when filtering by 'region', "
            "because region names are scoped to conditions."
        )
    # ... rest of implementation
```

### Option 2

Accept `region_id` directly as an alternative filter, bypassing the need for a condition. Since `region_id` is globally unique in the database, it can be used without a condition context:

```python
def get_cells(
    self,
    condition: str | None = None,
    region: str | None = None,
    region_id: int | None = None,
    is_valid: bool | None = None,
) -> list[CellInfo]:
    if region is not None and condition is None and region_id is None:
        raise ValueError(
            "When filtering by region name, a 'condition' is required. "
            "Alternatively, use 'region_id' to filter by region ID directly."
        )
    # ... build query with appropriate WHERE clauses
```

Also remove the redundant `cond_id` re-resolution on line 295.

## Technical Details

- File: `src/percell3/core/experiment_store.py`, `get_cells` method
- The root cause is that region names are scoped within conditions (the same region name can exist in different conditions), so a region name alone is ambiguous without a condition.
- The redundant `cond_id` re-resolution on line 295 should be removed regardless of which option is chosen.
- This finding interacts with Finding 005 (`get_cell_count` with opaque `**kwargs`): both methods need consistent filter handling.

## Acceptance Criteria

- [ ] `get_cells(region="r1")` without condition raises `ValueError` with a clear message
- [ ] `get_cells(condition="ctrl", region="r1")` continues to work correctly, returning only cells from that region
- [ ] Redundant `cond_id` re-resolution on line 295 is removed
- [ ] If `region_id` direct filtering is implemented (Option 2), it correctly filters without requiring condition
- [ ] Tests cover: region without condition (error case), region with condition (success), region_id alone (if implemented)
- [ ] `get_cell_count` has consistent behavior (see Finding 005)

## Work Log

### 2026-02-12 - Code Review Discovery

Identified during code review of `percell3.core`. The silent filter drop is a correctness hazard in scientific software where returning too many cells can lead to wrong biological conclusions. The redundant re-resolution suggests the filtering logic grew organically without a design pass.
