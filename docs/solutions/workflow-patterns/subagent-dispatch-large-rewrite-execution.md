---
title: "Subagent Dispatch for Large-Scale Rewrites"
category: workflow-patterns
tags: [percell4, rewrite, subagent-dispatch, compound-work, gate-execution, uuid-migration]
date: 2026-03-10
modules: [core, measure, segment, io, plugins, workflow, cli]
origin_plan: docs/plans/2026-03-10-rewrite-percell4-plan.md
origin_brainstorm: docs/brainstorms/2026-03-10-pbody-architecture-brainstorm.md
---

# Subagent Dispatch for Large-Scale Rewrites

## Summary

A 22,000-line rewrite (PerCell3 -> PerCell4) was executed in a single session using `/compound:work` subagent dispatch: 18 commits, 62 source files (11,296 LOC), 48 test files (10,786 LOC), 544 tests passing, across 12 steps in 4 gates. Post-implementation code simplicity review found only ~290 LOC (2.8%) of unnecessary complexity — the architecture was fully specified before any code was written.

## Context

PerCell3's int-PK data model couldn't support database merging (the lab's primary collaboration workflow). The rewrite replaced all integer PKs with UUID BLOB(16), introduced hexagonal two-layer architecture (ExperimentDB + LayerStore behind ExperimentStore facade), and ported all 7 modules including 7 plugins and 2 workflows.

This was the third architecture attempt after two prior iterations:
1. **Run-scoped refactor** (Feb 2026) — rejected as "confusing, not intuitive"
2. **Layer-based redesign** (Mar 2-3, 2026) — completed but insufficient for P-body workflow

The P-body architecture synthesized learnings from both, producing a fully specified design before execution.

## Execution Strategy

### Plan -> Review -> Gate -> Dispatch

1. **Plan:** 12-step plan with 134 checkboxes, 4 gates, kill criteria
2. **Review:** 19 specialized agents (10 research + 9 review) analyzed the plan pre-implementation, catching 8 critical and 12 serious findings
3. **Gate:** User approval at each gate boundary (Gate 0 -> Gate 1 -> Gate 2 -> Gate 3)
4. **Dispatch:** Each step dispatched to an independent general-purpose subagent

### Self-Contained Subagent Prompts

Each subagent received 6 components:

| Component | Purpose |
|-----------|---------|
| Plan file path | Canonical source of truth |
| Architecture doc path | Schema, design decisions |
| Prior commit context | What has already been built |
| Specific implementation instructions | Exactly what this step must produce |
| Test requirements | Minimum test coverage |
| Commit message | Pre-specified for consistent history |

No shared state between subagents — all communication via git commits.

### Dependency Tracking

TodoWrite with `blockedBy` relationships:
- Tasks 1b/1c/1d dispatched in parallel (separate files: schema.py, config.py, models.py)
- Tasks 5/6/7 dispatched in parallel (separate modules: measure, segment, io)
- Tasks 9/11 dispatched in parallel (plugins and workflows, separate directories)
- Tasks 15/17 dispatched in parallel (CLI and workflows)
- All other tasks sequential (each depends on prior commits)

### Dispatch Rules

- **Foreground by default** — sequential commits preserve clean git history
- **Parallel only** when steps touch completely separate files
- **Gate-by-gate user approval** — never auto-advance between gates
- **Code simplicity review** as Phase 3 quality gate after all steps complete

## Results

| Metric | Value |
|--------|-------|
| Source files | 62 |
| Source lines | 11,296 |
| Test files | 48 |
| Test lines | 10,786 |
| Tests passing | 544 |
| Commits | 18 |
| Code simplicity score | 2.8% potential reduction |
| Pre-implementation critical findings caught | 8 |
| Test-to-source ratio | 0.96 (nearly 1:1) |

## Key Patterns

### Pattern 1: One commit = one task = one subagent
The atomic unit of work is a single commit. Each commit is produced by exactly one subagent. No subagent modifies files it did not create (except imports in `__init__.py`).

### Pattern 2: Externalize all state to git
Subagents communicate exclusively through git commits. No shared memory, no message passing. The orchestrator reconstructs context from `git log` when needed. This makes the system resilient to context compaction.

### Pattern 3: Tests are mandatory per-step
Every step includes tests. The orchestrator verifies `pytest` passes after each subagent completes. This prevents test debt accumulation.

### Pattern 4: Pre-implementation review pays for itself
The 8 critical findings caught in the plan review would each have cost 1-3 steps of rework if discovered during implementation. The merge FK ordering issue (Critical #1) would have caused runtime failures on the first real merge.

### Pattern 5: Architecture spec before execution
The 2.8% unnecessary complexity rate is a direct result of fully specifying the architecture before writing any code. Both prior iterations (run-scoped, layer-based) had higher rework rates because designs evolved during implementation.

## Anti-Patterns to Avoid

- **Skipping architecture definition** — leads to mid-rewrite design pivots wasting 30-50% of dispatches
- **Parallel dispatch of steps sharing test fixtures** — causes merge conflicts
- **Not listing prior commits in subagent prompts** — subagent re-implements completed work
- **Amending commits instead of creating new ones** — destroys prior work when hooks fail

## When to Re-Read This

- Before running `/compound:work` on a plan with 50+ checkboxes
- When deciding subagent dispatch vs single-session coding (threshold: >5 files or >3 commits)
- When context compaction is likely mid-task
- Before any multi-module rewrite or port

## Invalidation Conditions

| Assumption | If invalidated... |
|---|---|
| TodoWrite state lost on compaction | Single-session becomes viable for larger plans |
| Context windows ~200K tokens | 10x growth makes single-session viable for most rewrites |
| Subagent dispatch ~5 min overhead | If overhead grows, batch more per dispatch |

## Knowledge Chain

```
Prior Refactors (2 iterations, 22 solution docs)
  -> Brainstorm Research
  -> P-Body Architecture Brainstorm (8 decisions)
  -> Plan Research (4 agents)
  -> Rewrite Plan (12 steps, 4 gates)
  -> Deepen Plan (19 agents: 8 critical findings)
  -> Implementation (18 commits, 544 tests)
  -> Code Simplicity Review (2.8% reduction)
  -> This Compound Document
```

## Cross-References

| Topic | Document |
|---|---|
| Why UUIDs | `docs/plans/uuid_vs_integer_agent_answer.md` |
| Architecture decisions | `docs/plans/percell4_architecture_decisions.md` |
| Prior refactor learnings | `docs/solutions/architecture-decisions/layer-based-architecture-redesign-learnings.md` |
| Derived FOV contract | `docs/solutions/design-gaps/derived-fov-lifecycle-coordination.md` |
| Plan review synthesis | `.workflows/deepen-plan/rewrite-percell4/run-1-synthesis.md` |
| Code quality assessment | `.workflows/work-review/code-simplicity.md` |
