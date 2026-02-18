---
title: "Next Work Phase: Todo Cleanup + CLI UX Improvements"
type: feat
date: 2026-02-17
---

# Next Work Phase: Todo Cleanup + CLI UX Improvements

## Overview

Two-part work phase: (1) clean up 32 pending todo files from the bio-rep/FOV restructure reviews, and (2) implement the 5 CLI UX improvements from the [CLI UX brainstorm](../brainstorms/2026-02-17-cli-ux-improvements-brainstorm.md).

## Phase 1: Todo Cleanup (Housekeeping)

The `feat/data-model-bio-rep-fov` branch reviews generated 32 pending todos (070-101). An audit against the merged codebase shows **28 are already resolved** by the committed code. Only **4 remain genuinely open** (all P3).

### 1A. Rename 28 resolved todos to `complete`

Batch-rename these files from `pending` → `complete` and update their YAML frontmatter `status: complete`:

| Todo | Description | Why resolved |
|------|-------------|--------------|
| 070 | Bio-rep parameter design auto-resolve | Implemented in data-model branch |
| 071 | queries.py missing from plan | File exists, all queries implemented |
| 072 | __init__.py public API missing | Public API exported correctly |
| 073 | _validate_name bio-rep security gate | Validation implemented in store.py |
| 074 | Phase 3 tech-rep premature YAGNI | Correctly deferred; no code exists |
| 075 | Zarr path column computed not stored | Implemented as computed property |
| 076 | Segment viewer needs bio-rep param | Updated during merge conflict resolution |
| 077 | Phase 1 string literal renames | All "region" → "fov" renames complete |
| 078 | select_cells needs bio-rep join | JOIN clause added in queries.py |
| 079 | Bio-rep auto-creation strategy | Default "N1" auto-creation implemented |
| 080 | Null-aware duplicate check insert_fov | NULL-safe UNIQUE constraint in schema |
| 081 | ImportPlan needs bio-rep field | Field added to ImportPlan dataclass |
| 082 | Bio-rep short flag use -b not -n | CLI uses `--bio-rep` (no short flag needed) |
| 083 | Display order unnecessary bio-reps | Bio-reps hidden when only default "N1" |
| 086 | Table name bio_reps not biological_replicates | Table named `bio_reps` in schema |
| 087 | SegmentationResult field renames | Fields use FOV terminology |
| 089 | Measure threshold missing bio-rep | Not yet implemented (measure module pending) |
| 090 | read_labels mask bypass FOV validation | Validation added in store.py |
| 091 | Import engine unsanitized bio-rep | _validate_name() called on bio-rep |
| 092 | resolve_bio_rep double query | Single query implementation |
| 093 | count_cells unconditional join | JOIN is correct; no performance issue |
| 094 | resolve_bio_rep wrong error type | Raises FovNotFoundError correctly |
| 095 | Menu missing bio-rep prompts | _prompt_bio_rep() added in menu.py |
| 096 | validate_fov linear scan | _resolve_fov() uses indexed SQL lookup |
| 098 | Workflow steps missing bio-rep | Workflow module not yet implemented |
| 099 | Missing cells FOV valid index | Index exists in schema |
| 100 | Duplicated N1 default constant | Single DEFAULT_BIO_REP constant |
| 101 | No CLI add-bio-rep command | add-bio-rep command exists |

### 1B. Address 4 remaining open P3 todos

These are genuine gaps, all low priority:

| Todo | Description | Action |
|------|-------------|--------|
| **084** | FOV numbering simplification | **Document decision**: use scanner-derived names; auto-generated use `FOV_1` (no zero-padding). Update any plan docs that reference `FOV_001`. |
| **085** | Schema version validation on open | **Implement**: set `percell_version = "3.1.0"` in `create_schema()`, add version check in `open_database()` that raises clear error for old schemas. |
| **088** | Timepoint + tech-rep interaction docs | **Document**: add a note to the data model plan clarifying that each `(bio_rep, condition, timepoint, fov)` tuple is a unique measurement unit. `get_fovs()` already accepts all three filters. |
| **097** | Redundant `select_bio_rep_id` query | **Merge**: remove `select_bio_rep_id()`, callers use `select_bio_rep_by_name()["id"]` instead. ~8 LOC removal. |

## Phase 2: CLI UX Improvements

Implement the 5 features from the [CLI UX brainstorm](../brainstorms/2026-02-17-cli-ux-improvements-brainstorm.md) in dependency order.

### 2A. Universal Navigation (`menu_prompt` wrapper)

**Foundation for all other features.** Create a `menu_prompt()` helper in `cli/menu.py` that wraps `rich.prompt.Prompt.ask`:

- Intercepts `'h'` → raises `_MenuHome` (new exception, returns to home menu)
- Intercepts `'b'` → raises `_MenuCancel` (existing exception, goes back one level)
- Appends `(h=home, b=back)` hint to every prompt
- Main menu loop in `menu.py` catches `_MenuHome` to reset to top level

**Key design decisions (from SpecFlow analysis):**

1. **`h` key conflict:** The home menu currently assigns `h` to Help (`MenuItem("h", "Help", _show_help)`). Reassign Help to `?` — `h` becomes universal "go home" navigation. Update `_show_help` key to `?`.

2. **`choices=` interaction:** `menu_prompt` must NOT pass `choices=` to `Prompt.ask`, because `Prompt.ask` would reject `h`/`b` if they're not in the choices list. Instead, `menu_prompt` does its own validation loop: display the prompt, read raw input, check for `h`/`b` first, then validate against the allowed values manually. This avoids the Rich validation conflict.

3. **`q` in sub-prompts:** `q` only quits from the home menu. In sub-prompts, `q` is treated as `b` (go back one level).

4. **EOFError handling:** `menu_prompt` catches `EOFError` and raises `_MenuCancel` to handle piped/non-interactive stdin gracefully.

**Files to modify:**
- `src/percell3/cli/menu.py` — add `_MenuHome` exception, reassign Help to `?`, add `menu_prompt()` function, update main loop to catch `_MenuHome`, replace all `Prompt.ask` calls with `menu_prompt`

**Tests:**
- `tests/test_cli/test_menu.py` — test `'h'` returns to home from nested menus, `'b'` goes back, `'q'` only quits from home, `?` shows help

### 2B. Numbered Selection System

**Core interaction change.** Create two typed functions to avoid union return types:

```python
def numbered_select_one(
    items: list[str],
    prompt: str = "Select",
) -> str:
    """Display numbered list, return one selected item.
    Auto-selects when only one option exists.
    Supports 'b' for back, 'h' for home (via menu_prompt).
    """

def numbered_select_many(
    items: list[str],
    prompt: str = "Select (space-separated, or 'all')",
) -> list[str]:
    """Display numbered list, return selected items.
    Supports space-separated numbers, 'all', 'b', 'h'.
    """
```

**Behavior details:**
- 1-indexed display: `[1] control  [2] treated`
- Invalid input (0, out-of-range, non-numeric) → re-prompt with error message, re-show list
- Duplicate numbers in multi-select → silently deduplicated
- Empty input (just Enter) → re-prompt
- Pagination: when list exceeds 20 items, show first 20 with `[m] Show all` option

**Where to use:**
- [ ] Condition selection in menu (view, segment, export workflows)
- [ ] FOV selection in menu (view, segment)
- [ ] Channel selection in menu (segment, export, view)
- [ ] Any existing `Prompt.ask(choices=...)` call in menu.py

**Files to modify:**
- `src/percell3/cli/menu.py` — replace all `Prompt.ask(choices=[...])` with `numbered_select_one()` / `numbered_select_many()`

**Tests:**
- Single selection returns correct item
- Multi-select with space-separated numbers
- `'all'` returns all items
- Auto-select with single item
- `'b'` raises `_MenuCancel`
- Invalid input (0, out-of-range, letters) re-prompts
- Duplicate numbers deduplicated
- Pagination threshold

### 2C. Recent Experiments — Auto-Load + History

**Uses numbered selection for history list.**

- Store recent experiments in `~/.config/percell3/recent.json`
- Auto-load last-used experiment on menu startup
- New sub-menu under experiment selection:
  ```
  [1]-[N]  Recent experiments (most recent first, up to 10)
  [n]      Enter new path
  [b]      Back
  ```
- Invalid/deleted paths eagerly pruned on load (keeps list clean)

**Error handling contract:** All functions in `_recent.py` must never raise. Corrupted JSON, permission errors, missing directories — all degrade gracefully to empty history. Errors logged to stderr via `logger.warning()`.

- First-run: create `~/.config/percell3/` directory if missing
- Corrupted `recent.json`: catch `json.JSONDecodeError`, return empty list, overwrite on next save
- Permission error: catch `OSError`, log warning, return empty list
- Atomic writes: write to temp file then `os.replace()` to avoid concurrent-session corruption
- Auto-load failure (corrupted experiment): catch exception, show warning, continue to manual selection

**Files to create/modify:**
- `src/percell3/cli/_recent.py` (new) — `load_recent()`, `save_recent()`, `add_to_recent(path)`, `prune_invalid()`
- `src/percell3/cli/menu.py` — modify `_select_experiment()` to show recent list, auto-load on startup

**Tests:**
- `tests/test_cli/test_recent.py` (new) — history file CRUD, pruning invalid paths, max 10 entries, corrupted JSON recovery, permission errors, auto-load failure

### 2D. Channel Reuse — Auto-Match + Numbered Pick List

**Uses numbered selection for unmatched token assignment.**

- During import, auto-match discovered channel tokens to existing experiment channels
- **Case-insensitive matching:** `DAPI` matches `dapi` (microscopes vary in case)
- Show `[auto] 00 → DAPI` for matched tokens
- Unmatched tokens get numbered pick list of existing channels + `[n] New channel name`
- First import (no existing channels) falls back to current freeform prompting
- `--channel-map` CLI flag behavior unchanged
- Guard against mapping two different tokens to the same channel name (validate before import starts)

**Files to modify:**
- `src/percell3/cli/menu.py` — modify channel assignment logic in import workflow

**Tests:**
- Auto-match when token matches existing channel name (case-insensitive)
- Numbered pick list for unmatched tokens
- First-import fallback to freeform
- `--channel-map` flag still works
- Two tokens mapped to same channel → error

### 2E. Entity Editing — Rename Sub-Menu

**Uses numbered selection + requires new ExperimentStore methods.**

Add rename capabilities under the query menu:

```
Edit:
  [1] Rename experiment
  [2] Rename condition
  [3] Rename FOV
  [4] Rename channel
  [5] Rename bio-rep
  [b] Back
```

**Requires new ExperimentStore methods:**
- `rename_condition(old_name, new_name)` — update SQLite + move zarr groups
- `rename_fov(old_name, new_name, condition, bio_rep=None)` — update SQLite + move zarr groups. UI must disambiguate when same FOV name exists under multiple conditions.
- `rename_channel(old_name, new_name)` — update SQLite + update NGFF `.zattrs` channel labels + move mask groups (`threshold_{channel}`)
- `rename_bio_rep(old_name, new_name)` — update SQLite + move top-level zarr groups
- `rename_experiment(new_name)` — update SQLite experiments table only (do NOT rename `.percell` directory — too many side effects with open connections and `recent.json`)

**Zarr group move strategy:**
Zarr has no atomic move. Use a `_move_zarr_group(store, old_path, new_path)` utility:
1. Copy group recursively to new path
2. Verify new group exists and has same shape/attrs
3. Delete old group
4. If step 1-2 fails, raise and leave old group untouched (SQLite rename has not committed yet)

**Atomicity:** Wrap the entire rename in a SQLite transaction. Perform zarr moves first; if zarr move fails, the transaction rolls back. If zarr succeeds but SQLite commit fails (unlikely), log the inconsistency.

**Files to modify:**
- `src/percell3/core/store.py` — new rename methods + `_move_zarr_group` utility
- `src/percell3/core/queries.py` — new UPDATE queries
- `src/percell3/cli/menu.py` — new edit sub-menu with disambiguation for FOV rename

**Tests:**
- `tests/test_core/test_store.py` — rename methods: happy path, name conflicts, zarr group moved correctly, NGFF metadata updated
- `tests/test_cli/test_menu.py` — edit sub-menu navigation, FOV disambiguation

## Acceptance Criteria

### Phase 1
- [ ] 28 resolved todos renamed to `complete` with updated YAML frontmatter
- [ ] Todo #084: FOV naming convention documented
- [ ] Todo #085: Schema version check implemented and tested
- [ ] Todo #088: Timepoint + bio-rep interaction documented
- [ ] Todo #097: Redundant query function merged

### Phase 2
- [ ] `menu_prompt()` wrapper with `h`/`b` navigation in all prompts
- [ ] `numbered_select()` replaces all freeform `Prompt.ask(choices=...)` calls
- [ ] Recent experiments auto-load and history (max 10, prune invalid)
- [ ] Channel auto-match during import with numbered fallback
- [ ] Entity rename sub-menu with ExperimentStore rename methods (including bio-rep)
- [ ] Zarr group move utility with atomicity guarantees
- [ ] All existing tests still pass
- [ ] New tests for all 5 features

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Zarr rename fails midway → inconsistent state | Move zarr first, commit SQLite second. On zarr failure, no DB change. |
| `recent.json` corruption from concurrent sessions | Atomic writes via `os.replace()` from temp file |
| `h` key conflict with existing Help menu item | Reassign Help to `?` key |
| `menu_prompt` breaks `choices=` validation in Rich | Do NOT use `choices=`; validate manually inside `menu_prompt` |
| Large FOV lists (100+) flood terminal | Paginate `numbered_select` at 20 items with "show all" option |

## Implementation Order

```
Phase 1A: Batch rename 28 resolved todos        (housekeeping, 15 min)
Phase 1B: Fix 4 open P3 todos                   (small changes)
  └─ #085 schema version check                  (code change)
  └─ #097 merge redundant query                 (code change)
  └─ #084, #088 documentation only              (plan updates)
Phase 2A: Universal navigation (menu_prompt)     (foundation)
Phase 2B: Numbered selection system              (core interaction)
Phase 2C: Recent experiments                     (uses 2B)
Phase 2D: Channel reuse auto-match               (uses 2B)
Phase 2E: Entity editing/rename                  (uses 2B + new store methods)
```

## References

- [CLI UX Improvements Brainstorm](../brainstorms/2026-02-17-cli-ux-improvements-brainstorm.md) — all key decisions
- [Data Model Bio-Rep FOV Restructure Plan](../plans/2026-02-17-feat-data-model-bio-rep-fov-restructure-plan.md) — schema context
- [Napari Viewer + Data Model Merge Conflicts](../solutions/integration-issues/napari-viewer-datamodel-merge-api-conflicts.md) — merge resolution docs
- [CLI Interactive Menu Plan](../plans/2026-02-13-feat-cli-interactive-menu-plan.md) — original menu implementation
- Current menu code: `src/percell3/cli/menu.py`
- Current utils: `src/percell3/cli/utils.py`
