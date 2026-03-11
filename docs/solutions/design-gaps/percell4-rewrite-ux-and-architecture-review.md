---
title: "PerCell4 Rewrite UX and Architecture Review"
date: 2026-03-10
category: design-gaps
severity: P1-P3
module: cli, viewer, core
tags: [ux, architecture, menu-system, interactive-cli, napari, review]
origin_plan: docs/plans/2026-03-10-feat-napari-viewer-pixel-size-plan.md
validated: true
---

# PerCell4 Rewrite — UX and Architecture Review

Comprehensive review of the `feat/percell4-gate0` branch (131 files, ~26K lines, 628 tests) surfacing UX gaps, architecture concerns, and functionality holes that prevent end-to-end usage.

## Context

The PerCell4 rewrite was completed in a single multi-session sprint using subagent dispatch. The rewrite covers: core (ExperimentStore/DB/LayerStore), I/O (TIFF/LIF import), segmentation (Cellpose), measurement, plugins (8 built-in), workflows (2 built-in), napari viewer (7 dock widgets), and CLI (Click commands + interactive menu). Testing revealed that while the code is architecturally sound, the interactive menu has critical usability gaps.

## Key Findings

### P1 Critical — Status-Locked Pipelines

**Problem:** The segment handler only processes FOVs in `imported` status; the measure handler only processes `segmented` status. Once a FOV transitions past these states, it cannot be re-processed from the menu or CLI.

**Impact:** Users who need to re-segment (e.g., after adjusting parameters) or re-measure (after adding new thresholds) are stuck. This is the most common real-world operation in microscopy analysis.

**Root cause:** Handlers use `get_fovs_by_status()` with a single status filter. The layer-based architecture already supports creating new segmentation/measurement entities without destroying old ones — the handlers just don't expose this.

**Fix pattern:**
```python
# Instead of:
fovs = store.db.get_fovs_by_status(exp["id"], FovStatus.imported)

# Allow multiple statuses or all FOVs with user selection:
fovs = store.db.get_fovs(exp["id"])
active = [f for f in fovs if f["status"] not in ("deleted", "error")]
# Then let user select which FOVs to process
```

### P1 Critical — No Condition Management

**Problem:** The TOML template doesn't include `[[conditions]]`, import handlers don't prompt for condition assignment, and there's no way to create/edit/delete conditions after experiment creation. All FOVs get `condition_id = NULL`.

**Impact:** Grouped analysis (the primary use case — comparing treated vs control) is impossible without conditions.

**Fix:** Add `[[conditions]]` to TOML template, prompt during import, add condition CRUD to the menu.

### P1 Critical — Plugin Parameters Not Prompted

**Problem:** `_make_plugin_runner()` calls `plugin.run(store, fov_ids)` with no parameter prompts. Plugins like `condensate_partitioning_ratio` need specific channel mappings to work correctly.

**Impact:** Plugins either fail or produce meaningless results when run from the menu.

**Fix:** Add a `get_required_parameters()` method to the plugin ABC, prompt in the menu runner.

### P2 — Viewer Bypasses ExperimentStore Facade

**Problem:** All 8 viewer widgets call `store.db.*` (30+ calls) and `store.layers.*` (10+ calls) directly, violating the hexagonal architecture principle where ExperimentStore is the only public interface.

**Pragmatic assessment:** ExperimentStore exposes `.db` and `.layers` as read-only properties, making this a "soft boundary" rather than a hard violation. For a codebase of this size (3-6 users), the maintenance cost is low. However, if the DB schema changes, every widget breaks.

**Decision:** Accept for now. If ExperimentDB's API changes significantly (e.g., the P-body architecture's `cell_identities` table), batch-update viewer calls then.

### P2 — Save-Edited-Labels Logic Embedded in Viewer

**Problem:** The `save_edited_labels()` function in `_viewer.py` directly creates pipeline runs, segmentation sets, and ROI inserts. This domain logic should be a public function callable from CLI, headless scripts, and the viewer.

**This was a known issue from the percell3 code review** (P1-058: "Private API Blocking Headless Operations"). It was documented in `docs/solutions/architecture-decisions/viewer-module-code-review-findings.md` but recurred in the percell4 rewrite.

**Lesson:** Known issues from prior reviews should be checked as a gate before completing new implementations. Consider adding a pre-completion checklist that references prior review findings for the same module.

### P2 — Missing Menu Features

Features available in CLI but not in the interactive menu:
1. `assignments` command — view active segmentation/mask assignments
2. Condition assignment during import
3. `--roi-type` filter on export
4. Workflow execution (particle analysis, decapping sensor)

### P3 — Duplicate TOML Templates

`cli/main.py:init` and `menu_handlers/setup.py:_generate_template_toml()` duplicate the TOML template with slight formatting differences. Extract to a shared function.

## What Was Verified OK

- **Data integrity:** Foreign keys ON, WAL mode, parameterized SQL, SAVEPOINT transactions
- **Security:** No injection, eval/exec, credentials, pickle usage
- **UUID consistency:** Centralized `new_uuid()`, BLOB(16) storage throughout
- **Test coverage:** 628 tests across all modules
- **Optional dependency handling:** napari and cellpose properly guarded

## Reuse Triggers

Re-read this document when:
- Adding new menu handlers (check: does it handle all FOV statuses?)
- Adding new plugins (check: does the menu runner prompt for parameters?)
- Modifying ExperimentDB API (check: viewer widget call sites)
- Implementing the P-body architecture (check: all P1 items resolved first)
- Before any code review of CLI/menu code (checklist of known patterns)

## Assumptions That Could Invalidate Findings

- If the project moves to a web UI, the menu UX findings become irrelevant
- If plugins get a separate parameter UI in napari, the menu parameter prompting is lower priority
- If condition management moves to a TOML-editing workflow, the menu CRUD isn't needed

## References

- Full review: `.workflows/code-review/percell4-rewrite/agents/comprehensive-review.md`
- Prior viewer review (percell3): `docs/solutions/architecture-decisions/viewer-module-code-review-findings.md`
- Layer-based architecture: `docs/solutions/architecture-decisions/layer-based-architecture-redesign-learnings.md`
- Subagent dispatch learnings: `docs/solutions/workflow-patterns/subagent-dispatch-large-rewrite-execution.md`
