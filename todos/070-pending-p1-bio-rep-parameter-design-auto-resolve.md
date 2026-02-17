---
status: pending
priority: p1
issue_id: "070"
tags: [plan-review, architecture, api-design]
dependencies: []
---

# Bio Rep Parameter Design: Eliminate `bio_rep="N1"` Hardcoded Default

## Problem Statement

The plan proposes adding `bio_rep: str = "N1"` as a default parameter on ~10 ExperimentStore I/O methods (write_image, read_image, write_labels, read_labels, write_mask, read_mask, get_cells, get_cell_count, export_csv). Three independent reviewers flagged this as the plan's biggest design problem.

## Findings

- **Python reviewer**: "It hides bugs. If a caller forgets to pass bio_rep, the code silently operates on N1." Violates explicit-over-implicit.
- **Simplicity reviewer**: "The FOV already knows its bio_rep" via bio_rep_id FK. The store can look up the bio rep from the database rather than requiring every caller to pass it.
- **Architecture strategist**: Recommends a FovRef value object `@dataclass(frozen=True) class FovRef: fov: str, condition: str, bio_rep: str = "N1", timepoint: str | None = None` to bundle parameters instead of 4+ loose strings.

## Proposed Solutions

### A) Auto-resolve pattern

Use `bio_rep: str | None = None` on all methods. When None and exactly 1 bio rep exists, auto-resolve. When None and N2+ exists, raise ValueError.

- **Pros**: Simple-case stays simple, explicit when ambiguous.
- **Cons**: Slightly more complex _resolve_fov() logic.
- **Effort**: Small.
- **Risk**: Low.

### B) FovRef value object

Create a FovRef dataclass, pass it to all I/O methods.

- **Pros**: Eliminates parameter explosion, future-proof.
- **Cons**: New abstraction, callers must construct FovRef.
- **Effort**: Medium.
- **Risk**: Low.

### C) Resolve bio_rep from FOV record

Since FOV's bio_rep_id is stored, _resolve_fov() can look up the bio rep from (fov_name, condition). No bio_rep param on I/O methods at all — only on add_fov() and get_fovs().

- **Pros**: Minimal API change.
- **Cons**: FOV_001 may exist in N1 and N2, so ambiguous.
- **Effort**: Small.
- **Risk**: Medium (ambiguity).

## Technical Details

Affected file: `src/percell3/core/experiment_store.py` — 10+ methods. Also affects segment engine, measure module, viewer, CLI.

## Acceptance Criteria

- [ ] No I/O method has `bio_rep="N1"` hardcoded default
- [ ] Simple experiments (1 bio rep) work without specifying bio_rep
- [ ] Multi-bio-rep experiments raise clear error if bio_rep is ambiguous

## Work Log

- 2026-02-17 — Identified by Python reviewer, simplicity reviewer, architecture strategist during plan review

## Resources

- Plan: docs/plans/2026-02-17-feat-data-model-bio-rep-fov-restructure-plan.md
