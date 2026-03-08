---
status: complete
priority: p3
issue_id: "088"
tags: [plan-review, architecture, completeness]
dependencies: []
---

# Timepoint + Bio Rep Interaction

## Problem Statement

The plan does not specify how timepoints interact with the bio rep layer.

## Resolution

**Documented: each `(bio_rep, condition, timepoint, fov)` tuple is a unique measurement unit.**

### Data model clarification

1. **Zarr path hierarchy** (deliberate design choice):
   ```
   experiment.zarr/
     bio_rep/
       condition/
         timepoint/
           FOV/
             channel/
   ```

2. **`get_fovs()` signature** already accepts all three optional keyword filters:
   ```python
   def get_fovs(
       self,
       condition: str | None = None,
       bio_rep: str | None = None,
       timepoint: str | None = None,
   ) -> list[FovInfo]
   ```
   All three can be combined to narrow the query.

3. **PER_FOV mode**: Each `(bio_rep, condition, timepoint, fov)` tuple is a unique measurement unit. Measurements are computed per-cell within each FOV.

4. **POOLED mode** (future): All FOVs within a `(bio_rep, condition, timepoint)` group would be pooled. Timepoints are NOT pooled across — each timepoint forms its own grouping context.

5. **Phase 3 tech rep grouping** (deferred): If implemented, tech rep grouping would operate within a `(bio_rep, condition, timepoint)` context, not across timepoints.

## Work Log

- 2026-02-17: Identified during plan review
- 2026-02-18: Documented interaction rules. Verified get_fovs() already has all three filters. Marked complete.
