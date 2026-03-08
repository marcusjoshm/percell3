---
status: pending
priority: p2
issue_id: "005"
tags: [code-review, quality]
dependencies: []
---

# get_cell_count Uses Opaque **kwargs

## Problem Statement

`ExperimentStore.get_cell_count()` accepts `**filters: object` instead of explicit keyword arguments. This provides no type safety, no IDE autocompletion, and silently ignores filter keys that callers might reasonably expect to work (e.g., `region_id`, `is_valid`). The implementation manually parses only the `"condition"` key and discards everything else, meaning callers who pass other filters get silently incorrect results.

## Findings

- `experiment_store.py:325-329` defines `get_cell_count(**filters: object)` with an opaque signature.
- The implementation manually checks for the `"condition"` key and ignores all other keys.
- `region_id` and `is_valid` filters are not supported, even though they are meaningful filtering dimensions.
- The sibling method `get_cells()` has explicit keyword arguments, making the inconsistency confusing.
- A caller writing `get_cell_count(region_id=5, is_valid=True)` would receive a count of ALL cells with no indication that filtering was skipped.

## Proposed Solutions

### Option 1

Replace `**filters: object` with explicit keyword arguments that match the `get_cells` signature:

```python
def get_cell_count(
    self,
    condition: str | None = None,
    region: str | None = None,
    region_id: int | None = None,
    is_valid: bool | None = None,
) -> int:
```

Build the SQL query dynamically based on which arguments are provided, mirroring the filtering logic in `get_cells`.

### Option 2

Extract a shared `_build_cell_filter_clause()` helper that both `get_cells` and `get_cell_count` use, ensuring filter semantics stay in sync between the two methods.

## Technical Details

- File: `src/percell3/core/experiment_store.py`, lines 325-329
- The fix is a signature change, so all call sites must be audited. Since the method currently only respects `condition`, existing callers passing `condition=` will continue to work unchanged.
- Any callers passing other keyword arguments are currently broken (silently ignored), so fixing them is strictly an improvement.

## Acceptance Criteria

- [ ] `get_cell_count` has explicit, typed keyword arguments instead of `**filters`
- [ ] `region_id` and `is_valid` filters are supported and produce correct counts
- [ ] Passing `region` without `condition` either works or raises a clear error (consistent with `get_cells` behavior)
- [ ] Type checkers (mypy/pyright) can verify call sites
- [ ] Unit tests cover each filter dimension individually and in combination

## Work Log

### 2026-02-12 - Code Review Discovery

Identified during code review of `percell3.core`. The opaque `**filters` pattern defeats static analysis and silently drops filters, creating a correctness risk for any caller that assumes filters are applied.
