---
status: complete
priority: p2
issue_id: "074"
tags: [plan-review, yagni, architecture]
dependencies: []
---

# Phase 3 TechRepMode Enum is Premature YAGNI

## Problem Statement

Phase 3 (TechRepMode enum + configurable tech rep grouping) is a YAGNI violation. The measure/statistics module doesn't exist yet. Building statistics infrastructure before the statistics module exists is premature.

## Findings

- **Simplicity reviewer**: "This enum and its associated grouping logic should be deferred entirely until the statistics module is built. At that point, it becomes a simple parameter to the statistics function, not a schema-level concept."
- **Architecture strategist**: "The TechRepMode interaction with timepoints is not specified."
- **Spec-flow**: "What aggregation function? Mean, median, sum, count? Not specified."

## Proposed Solutions

### A) Defer Phase 3 entirely

Remove Phase 3 from the current plan. Implement tech rep grouping when the measure/statistics module is built.

- **Pros**: Zero effort now, avoids speculative design.
- **Cons**: None — the feature isn't needed yet.
- **Effort**: Zero (removal).
- **Risk**: None.

### B) Keep Phase 3 as documented future work

Keep Phase 3 in the plan but mark it explicitly as "future work" with no implementation now.

- **Pros**: Documents the intent for future developers.
- **Cons**: May create pressure to implement prematurely.
- **Effort**: Small.
- **Risk**: Low.

## Technical Details

Phase 3 proposes:
- `TechRepMode` enum with values like `PER_FOV`, `MEAN_ACROSS_FOVS`, etc.
- Grouping logic that aggregates measurements across FOVs within a bio rep
- Integration with `get_measurement_pivot()` and export

None of these have consumers yet. The measure module (Module 4) and statistics plugins have not been built.

## Acceptance Criteria

- [ ] Phase 3 removed from current plan or explicitly marked as deferred
- [ ] No TechRepMode enum created until statistics module is ready
- [ ] Plan document updated to reflect deferral decision

## Work Log

- 2026-02-17 — Identified by simplicity reviewer, architecture strategist, and spec-flow during plan review

## Resources

- Plan: docs/plans/2026-02-17-feat-data-model-bio-rep-fov-restructure-plan.md
