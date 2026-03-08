---
status: complete
priority: p2
issue_id: "076"
tags: [plan-review, agent-native, api-design]
dependencies: []
---

# SegmentationEngine.run() and launch_viewer() Need Explicit bio_rep Parameters

## Problem Statement

`SegmentationEngine.run()` and `launch_viewer()` need explicit bio_rep parameters but the plan only vaguely mentions this in Phase 2.7 without specifying the API.

## Findings

- **Agent-native reviewer**: "Without bio_rep on run() and launch_viewer(), the CLI would need to resolve bio_rep -> FOV list itself (duplicating logic), or the API would lack the capability that the CLI offers."
- Currently `SegmentationEngine.run()` at `segment/_engine.py:38` takes `regions` and `condition` but not `bio_rep`.
- `launch_viewer()` takes `(store, region, condition, channels)` — no bio_rep.

## Proposed Solutions

### A) Add bio_rep parameter to both methods

Add `bio_rep: str | None = None` parameter to `SegmentationEngine.run()` and `launch_viewer()`. Internal filtering via `get_fovs(bio_rep=bio_rep)`. Follows the existing condition filtering pattern.

- **Pros**: Consistent with existing API patterns, clean delegation from CLI.
- **Cons**: Another optional parameter on already-parameterized methods.
- **Effort**: Small.
- **Risk**: Low.

### B) Accept FovRef value object (if adopted from issue 070)

If FovRef is adopted, pass it instead of loose parameters.

- **Pros**: Clean API, future-proof.
- **Cons**: Depends on issue 070 decision.
- **Effort**: Medium.
- **Risk**: Low.

## Technical Details

Affected files:
- `src/percell3/segment/_engine.py` — `SegmentationEngine.run()`
- `src/percell3/segment/_viewer.py` — `launch_viewer()`
- `src/percell3/cli/segment_cmd.py` — CLI `--bio-rep` flag delegation

Current signatures:
- `run(self, regions: list[str] | None, condition: str, ...)` — needs `bio_rep: str | None = None`
- `launch_viewer(store, region, condition, channels)` — needs `bio_rep: str | None = None`

## Acceptance Criteria

- [ ] `SegmentationEngine.run()` accepts bio_rep parameter
- [ ] `launch_viewer()` accepts bio_rep parameter
- [ ] CLI `--bio-rep` flag delegates cleanly to API methods
- [ ] When bio_rep is None and only one exists, auto-resolve (matching issue 070 pattern)

## Work Log

- 2026-02-17 — Identified by agent-native reviewer during plan review

## Resources

- Plan: docs/plans/2026-02-17-feat-data-model-bio-rep-fov-restructure-plan.md
- Related: todos/070-pending-p1-bio-rep-parameter-design-auto-resolve.md
