---
status: pending
priority: p2
issue_id: "079"
tags: [plan-review, architecture, ux]
dependencies: []
---

# Bio Rep Auto-Creation Strategy Not Decided

## Problem Statement

The plan raises but does not answer: should bio reps be auto-created during import (like conditions) or require explicit creation first? There is also no CLI command for creating bio reps outside of import.

## Findings

- **Spec-flow**: "The current pattern is inconsistent: conditions ARE auto-created during import (engine.py lines 85-99)."
- **Agent-native**: "An automated pipeline needs to create the bio rep hierarchy before importing images."
- Plan says "Bio rep assignment is always explicit (--bio-rep flag)" but doesn't say if the bio rep must pre-exist.

## Proposed Solutions

### A) Auto-create on import (matching condition pattern)

If `--bio-rep N2` is passed and N2 doesn't exist, auto-create it. Matches the existing condition auto-creation pattern.

- **Pros**: Ergonomic, consistent with condition behavior, fewer steps for users.
- **Cons**: Typos silently create new bio reps (e.g., `--bio-rep n2` vs `--bio-rep N2`).
- **Effort**: Small.
- **Risk**: Low.

### B) Require explicit creation first

Add `percell3 add-bio-rep` CLI command or `store.add_bio_rep()` call. Import fails if bio rep doesn't exist.

- **Pros**: Explicit, catches typos immediately, bio rep names are validated upfront.
- **Cons**: Extra step in workflow, breaks simple single-command import.
- **Effort**: Small.
- **Risk**: Low.

### C) Auto-create with confirmation in interactive mode

Auto-create silently in non-interactive (scripted) mode. In interactive CLI mode, prompt for confirmation: "Bio rep 'N2' does not exist. Create it? [Y/n]".

- **Pros**: Best of both worlds — safe interactive use, scriptable automation.
- **Cons**: More complex implementation, two code paths.
- **Effort**: Medium.
- **Risk**: Low.

## Technical Details

Current condition auto-creation pattern (`io/engine.py` lines 85-99):
- `_ensure_condition()` checks if condition exists, creates if not
- No confirmation prompt, always auto-creates
- Works well for automation

For bio reps, the decision affects:
- `ImportEngine.execute()` — where in the pipeline is bio_rep resolved?
- `store.add_fov()` — does it require bio_rep_id or auto-create?
- CLI `import` command — does `--bio-rep` flag auto-create or require pre-existing?
- `percell3 add-bio-rep` command — needed if explicit creation required

## Acceptance Criteria

- [ ] Plan specifies whether bio reps are auto-created or require explicit creation
- [ ] Decision documented in plan and brainstorm
- [ ] If auto-create: add `_ensure_bio_rep()` helper matching `_ensure_condition()` pattern
- [ ] If explicit: add `percell3 add-bio-rep` CLI command and `store.add_bio_rep()` method

## Work Log

- 2026-02-17 — Identified by spec-flow and agent-native reviewers during plan review

## Resources

- Plan: docs/plans/2026-02-17-feat-data-model-bio-rep-fov-restructure-plan.md
