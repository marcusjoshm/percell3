---
status: complete
priority: p2
issue_id: "112"
tags: [code-review, core, dry, refactor]
dependencies: []
---

# Group tag DataFrame merge pattern duplicated 3 times

## Problem Statement

The same 8-10 line group tag merge-and-fillna pattern is copy-pasted in:
1. `get_measurement_pivot()` lines 531-542
2. `export_prism_csv()` lines 938-951
3. `export_particles_csv()` lines 1104-1115

All three do: get_cell_group_tags → DataFrame.from_dict → reset_index → merge → fillna.

## Findings

- **Found by:** kieran-python-reviewer, code-simplicity-reviewer
- **Location:** `src/percell3/core/experiment_store.py`

## Proposed Solutions

### Solution A: Extract private helper method (Recommended)
```python
def _merge_group_tags(self, df, cell_id_column="cell_id"):
    cell_ids = df[cell_id_column].unique().tolist()
    group_tags = self.get_cell_group_tags(cell_ids)
    if not group_tags:
        return df, []
    group_df = pd.DataFrame.from_dict(group_tags, orient="index")
    group_df.index.name = cell_id_column
    group_df = group_df.reset_index()
    df = df.merge(group_df, on=cell_id_column, how="left")
    group_cols = [c for c in group_df.columns if c != cell_id_column]
    for col in group_cols:
        if col in df.columns:
            df[col] = df[col].fillna("")
    return df, group_cols
```
- **Effort:** Small | **Risk:** Low | **Saves:** ~16 LOC

## Acceptance Criteria

- [ ] Single `_merge_group_tags()` method on ExperimentStore
- [ ] All 3 export paths use the helper
- [ ] Existing tests still pass

## Work Log

- 2026-02-25: Identified during code review
