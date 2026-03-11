---
title: "PerCell4 Completion — Subagent Dispatch Execution Learnings"
date: 2026-03-11
module: core, plugins, cli, workflow
tags:
  - subagent-dispatch
  - schema-migration
  - nan-handling
  - lineage-model
  - derived-fov
  - percell4-completion
  - large-rewrite
severity: informational
origin_plan: docs/plans/2026-03-10-feat-percell4-completion-plan.md
origin_brainstorm: docs/brainstorms/2026-03-10-percell4-completion-brainstorm.md
---

# PerCell4 Completion — Subagent Dispatch Execution Learnings

**Scope:** 9 steps, 9 commits (9d72760..ece32ae), ~6500 lines changed, 2092 tests passing, 0 failures.
**Prior:** Sequel to `subagent-dispatch-large-rewrite-execution.md` (12-step rewrite, 544 tests).

---

## 1. Execution Pattern

Sequential foreground subagent dispatch via beads issue tracking. Orchestrator never writes code.

**Each subagent prompt contained:**
- Plan path with step-specific checkboxes
- Reference files to read
- Prior commit context
- Specific tasks and test expectations
- Commit message template

**Commit cadence:** One commit per step. Each subagent ran tests before committing. No fixup commits needed. Linear dependency chain — no parallelism possible due to shared files (schema.py, models.py, experiment_store.py).

```
Step 1: 9d72760 test(spike): NaN validation          -- pure validation, no prod code
Step 2: c2fe7dc feat(schema): schema 6.0.0            -- DDL, migration, models
Step 3: 2cd17ca feat(core): lineage CRUD               -- depends on schema
Step 4: c2be542 test(core): test updates               -- depends on CRUD
Step 5: 2d3c837 feat(cli): banner + UX fixes           -- depends on CRUD
Step 6: f93da47 feat(cli): menu reorganization          -- depends on UX fixes
Step 7: 61b1b11 feat(plugins): plugin updates           -- depends on lineage CRUD
Step 8: e9f93a8 feat(plugins): threshold_bg_sub         -- depends on plugin infra
Step 9: ece32ae feat(workflow): workflow config          -- depends on plugins + menu
```

---

## 2. Key Technical Decisions

### 2a. NaN Spike Validated Single-Derived-FOV Approach

53 tests proved NaN pixels are viable through the full pipeline with these mitigations:
- **SQLite stores NaN as NULL** — `measurements.value` changed from `REAL NOT NULL` to `REAL` (nullable)
- **`scipy.ndimage.label` treats NaN as foreground** — must replace NaN with 0 before labeling
- **Area metric needs `mask & ~np.isnan(image)`** — original `np.sum(mask)` overcounts
- **Zarr `fill_value` defaults to 0.0** — derived FOVs must set `fill_value=float('nan')`
- **Performance acceptable:** worst case 7x slowdown for nanmean at 50% NaN on 2048x2048, absolute time 22ms
- **NumPy 2.x:** `np.nanmax`/`np.nanmin` on all-NaN return NaN with RuntimeWarning (not ValueError)

### 2b. Schema 6.0.0 Delta Was Much Smaller Than Planned

The brainstorm estimated 30-50% test breakage. In reality:
- `rois`, `cell_identities`, `fov_status_log`, `pipeline_runs` already existed in 5.1.0
- Actual delta: 5 new columns on `fovs` + FK cascade rules + nullable measurements.value + lineage_path index
- Test breakage: ~5-10%, not 30-50%

**Lesson:** Always diff planned schema changes against actual current schema. The deepen-plan review (13 agents) caught this scope error before execution.

### 2c. Cell Identities Preserved Across Derived FOVs

Cell identities are created ONCE at segmentation, then REUSED (same `cell_identity_id`) across all derived FOVs. This is the foundation of cross-lineage queries.

Original plan wording said "create cell_identities" — corrected to "PRESERVE existing cell_identity_id" during review.

### 2d. nan_zero Absorbed Into image_calculator

`nan_zero` became a `zero_to_nan` mode in image_calculator. The decapping_sensor workflow updated accordingly.

### 2e. threshold_bg_subtraction Redesign

Old (percell3): Multiple derived FOVs per parent (one per intensity group).
New (percell4): Single derived FOV per parent. Per-group BG estimated from dilute-phase pixels via histogram peak detection. Each cell subtracted by its group's BG. NaN outside ROIs. Core math separated into `_core.py`.

### 2f. Status Transitions Made Permissive

Added re-processing transitions (`measured→segmented`, `measured→imported`, `segmented→imported`). Status is informational, not a workflow gate. Handlers show all active FOVs.

### 2g. Derived FOV Contract Atomicity

The 4-step contract (create FOV, copy config, duplicate ROIs, measure) wrapped in `db.transaction()`. `pixel_size_um` now copied from source FOV (was silently omitted, corrupting physical measurements).

---

## 3. What Was Rejected

| Rejected Approach | Reason |
|---|---|
| Multi-derived-FOV for threshold_bg_subtraction | NaN spike proved single-FOV viable |
| Plugin parameter ABC (`get_parameter_schema()`) | Per-plugin custom menu handlers are simpler |
| TEXT UUIDs (from P-body spec) | Codebase standardized on BLOB(16) |
| `workflow_configs` in Step 2 | YAGNI — deferred to Step 6 when consumed |

---

## 4. Reusable Patterns

### 4a. Spike-Before-Commit

Step 1 (NaN spike) was pure validation: 53 tests, no production code. Discovered 4 critical issues that would have been expensive to find later. **Use when:** an architectural assumption is load-bearing across multiple modules.

### 4b. Deepen-Plan Catches Scope Errors

The 13-agent + red team review caught the most impactful issue (schema delta scope) before any code was written. **Lesson:** Multi-perspective plan review is highest-ROI for plans referencing existing code.

### 4c. Schema Migration With Backup

```
1. Copy DB file before migration
2. Execute in explicit transaction
3. PRAGMA foreign_key_check post-migration
4. On failure: restore from backup
```

### 4d. Core Math Separation

Plugins with algorithms benefit from `_core.py` (pure math) + plugin class (store I/O). Enables unit testing without database fixtures.

### 4e. Bulk Operations for Derived FOVs

`insert_rois_bulk()` using `executemany()` instead of N+1 individual inserts.

---

## 5. What Worked vs. What Could Improve

### Worked Well
- NaN spike as gate (prevented 8 steps on broken assumption)
- Red team after synthesis (caught 2 CRITICAL the panel missed)
- 1-commit-per-step (clean rollback, trivial bisection)
- beads tracking (persistent checklist independent of conversation context)

### Could Improve
- **Measurement engine gap:** `dispatch_measurements()` left as stub — plan acknowledged it but treated acknowledgment as resolution. Plugins must manually call `measure_fov()`.
- **Viewer module unscoped:** 37 `store.db.*` calls identified but not verified end-to-end
- **Plan written from spec, not from code:** Schema delta estimated from architecture doc, not from `git diff`
- **Contradictory wording across steps:** Step 5a corrected but Steps 5c/5d/5e retained old wording

---

## 6. Active Risks

| Risk | Severity | Mitigation |
|---|---|---|
| No integration tests for full workflow (import→export) | HIGH | Add 2-3 end-to-end tests per workflow |
| `dispatch_measurements()` is a stub | MEDIUM | Wire to actual measurement engine or document manual pattern |
| FK cascade on assignment tables untested | MEDIUM | Add deletion + `foreign_key_check` tests |
| `lineage_path` invalid on mid-tree FOV deletion | MEDIUM | Use ON DELETE RESTRICT on `parent_fov_id` |
| No menu handler smoke tests | MEDIUM | Test each handler with mocked input |
| `PRAGMA trusted_schema=OFF` blocks debug views | LOW | Document in schema.py comments |

---

## 7. Related Documents

| Document | Connection |
|---|---|
| `docs/solutions/workflow-patterns/subagent-dispatch-large-rewrite-execution.md` | Prior execution (rewrite phase) |
| `docs/brainstorms/2026-03-10-percell4-completion-brainstorm.md` | Origin brainstorm |
| `docs/plans/2026-03-10-feat-percell4-completion-plan.md` | Implementation plan |
| `.workflows/nan-spike-results.md` | NaN spike findings |
| `.workflows/deepen-plan/feat-percell4-completion/run-1-synthesis.md` | 13-agent review synthesis |
| `docs/solutions/architecture-decisions/nan-zero-plugin-and-nan-safe-metrics.md` | NaN-safe metrics (percell3) |
| `docs/solutions/design-gaps/derived-fov-lifecycle-coordination.md` | 4-step derived FOV contract |
| `docs/solutions/architecture-decisions/layer-based-architecture-redesign-learnings.md` | Layer-based architecture |
