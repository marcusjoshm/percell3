---
status: pending
priority: p3
issue_id: "088"
tags: [plan-review, architecture, completeness]
dependencies: []
---

# Timepoint + Tech Rep Interaction

## Problem Statement

The plan does not specify how timepoints interact with the tech rep grouping or the bio rep layer in general.

## Findings

- Architecture strategist: "For PER_FOV mode, is each (bio_rep, condition, fov, timepoint) a separate row? For POOLED mode, are all timepoints also pooled?"
- Python reviewer: "The current timepoint-before-FOV path layout is consistent but should be documented as a deliberate choice."
- Spec-flow: "get_fovs() filtering with both bio_rep AND timepoint not specified."

## Proposed Solutions

### A) Add timepoint + bio_rep interaction documentation to the plan

- **Effort:** Small
- **Risk:** None

Add a dedicated section to the plan that documents:

1. The timepoint position in the zarr path hierarchy is a deliberate design choice (timepoint comes before FOV in the path).
2. get_fovs() accepts bio_rep, condition, and timepoint as optional filters — all three can be combined.
3. If Phase 3 (tech rep grouping) is kept, specify how timepoints affect grouping: are timepoints grouped independently within each bio_rep, or does each (bio_rep, timepoint) pair form its own grouping context?

## Technical Details

The zarr path layout is currently:

```
experiment.zarr/
  condition/
    timepoint/
      FOV/
        channel/
```

This means each FOV exists within a specific (condition, timepoint) context. When bio_reps are added as a layer above conditions, the full hierarchy becomes:

```
experiment.zarr/
  bio_rep/
    condition/
      timepoint/
        FOV/
          channel/
```

The plan needs to clarify:

- **PER_FOV mode:** Each (bio_rep, condition, timepoint, fov) tuple is a unique measurement unit.
- **POOLED mode:** All FOVs within a (bio_rep, condition, timepoint) are pooled, OR all FOVs within a (bio_rep, condition) across all timepoints are pooled? The former is more likely correct.
- **get_fovs() signature:** Should accept `bio_rep: str | None`, `condition: str | None`, `timepoint: str | None` as optional keyword filters.

## Acceptance Criteria

- [ ] Plan documents timepoint + bio_rep interaction
- [ ] get_fovs() signature includes all three optional filters

## Work Log

_No work performed yet._

## Resources

- Plan review: architecture strategist, Python reviewer, spec-flow feedback
- Current zarr layout: `src/percell3/core/store.py`
