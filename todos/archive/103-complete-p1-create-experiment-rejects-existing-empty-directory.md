---
status: complete
priority: p1
issue_id: "103"
tags: [code-review, core, ux, bug]
dependencies: []
---

# Create experiment rejects existing directories (even empty ones)

## Problem Statement

`ExperimentStore.create()` raises `ExperimentError("Path already exists: {path}")` if the target directory exists at all — including empty directories. This is a usability bug: users often create the directory first, then try to initialize an experiment in it. The current behavior forces users to pick a path that doesn't exist yet, which is confusing.

The fix should:
1. Allow creating experiments in existing **empty** directories without error
2. Warn and prompt for confirmation when the directory exists and is **non-empty** (overwrite)
3. When overwriting, delete the old contents before initializing

## Findings

- **Found by:** User testing
- **Location:** `src/percell3/core/experiment_store.py:94` — `if path.exists(): raise ExperimentError(...)`
- **Menu handler:** `src/percell3/cli/menu.py:620` — `_create_experiment()` catches ExperimentError but doesn't offer overwrite

## Proposed Solutions

### Solution A: Fix ExperimentStore.create() + add overwrite parameter (Recommended)
1. Add `overwrite: bool = False` parameter to `ExperimentStore.create()`
2. If path exists and is empty → proceed (skip `path.mkdir()`)
3. If path exists and is non-empty and `overwrite=False` → raise ExperimentError
4. If path exists and is non-empty and `overwrite=True` → delete contents, then proceed
5. Update `_create_experiment()` menu handler to detect existing dir and prompt user
- **Effort:** Small | **Risk:** Low (only changes creation flow, doesn't affect open)

### Solution B: Only fix menu handler
- Keep ExperimentStore.create() strict
- In `_create_experiment()`, check if dir exists and handle pre-deletion in the menu
- **Effort:** Small | **Risk:** Low

## Acceptance Criteria

- [ ] Empty existing directory accepted without error
- [ ] Non-empty existing directory prompts for overwrite confirmation
- [ ] Overwrite deletes old contents before creating new experiment
- [ ] CLI `percell3 create` also handles existing directories gracefully
- [ ] Test: create in empty dir, create with overwrite, create in non-existent dir

## Work Log

- 2026-02-25: Identified during user interface testing
