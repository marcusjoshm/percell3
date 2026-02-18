---
title: "Merge Conflict Resolution: napari-viewer + data-model-bio-rep-fov Feature Branches"
date: 2026-02-17
category: integration-issues
tags:
  - git-merge
  - feature-branch
  - api-migration
  - napari-viewer
  - data-model
  - fov-rename
  - bio-rep
severity: medium
components:
  - segment/viewer
  - segment/roi_import
  - cli/view
  - cli/menu
problem_type: merge_conflict_resolution
---

# Merge Conflict Resolution: napari-viewer + data-model-bio-rep-fov

## Problem Statement

Two feature branches developed in parallel had non-trivial API incompatibilities when merging into `main`:

- **`feat/napari-viewer`** (7 commits): Added a napari viewer module using the old "region" terminology and a positional-argument `store_labels_and_cells(store, labels, region, condition, run_id, region_id, pixel_size_um)` signature.
- **`feat/data-model-bio-rep-fov`** (6 commits): Renamed "region" to "FOV" throughout the codebase, added a `bio_rep` parameter, and changed `store_labels_and_cells` to accept a `FovInfo` object instead of positional `region_id`/`pixel_size_um` arguments.

Git reported textual conflicts in only 2 files (`menu.py`, `roi_import.py`), but the **semantic incompatibility was much broader** — the entire viewer module, CLI view command, and all viewer tests needed updating because the napari branch had never seen the FOV/bio_rep API.

## Root Cause

The two branches evolved the same underlying data model in incompatible directions simultaneously. The napari-viewer branch was developed against the old "region"-based API. The data-model branch replaced that API entirely with a new `FovInfo`-object-based calling convention and renamed all terminology from "region" to "FOV". Git's automatic conflict detection only catches textual overlaps, not semantic API drift across function signatures, parameter names, and calling conventions.

## Solution

### Merge Strategy

1. Merged `feat/napari-viewer` **first** using `git merge --no-ff` (clean merge, no conflicts).
2. Merged `feat/data-model-bio-rep-fov` **second** (conflicts in 2 files, plus 4 additional files needing manual update).

### Step-by-Step Resolution

#### 1. `menu.py` conflict (1 conflict region)

- **HEAD (napari)**: Had `_view_napari()` function using `store.get_regions()`, `region` variable names
- **bio-rep branch**: Had `_prompt_bio_rep()` helper function
- **Resolution**: Kept BOTH functions. Updated `_view_napari` to call `store.get_fovs()`, invoke `_prompt_bio_rep()`, and pass `bio_rep` to `launch_viewer()`.

#### 2. `roi_import.py` conflicts (4 conflict regions)

- **Imports**: HEAD had `RegionInfo, extract_cells`; bio-rep had `FovNotFoundError, FovInfo, LabelProcessor`. Resolution: Used bio-rep imports.
- **`store_labels_and_cells` signature**: Merged into `(store, labels, fov_info, fov, condition, run_id, timepoint=None, bio_rep=None) -> int`. Kept function **public** (no underscore prefix) because the viewer imports it. Kept return type as `int` (cell count).
- **`import_labels` and `import_cellpose_seg` call sites**: Updated to use new signature with keyword arguments.

#### 3. `viewer/__init__.py` (no git conflict, manual update required)

```python
# Before (napari branch)
def launch_viewer(store, region, condition, channels=None) -> int | None:
def save_edited_labels(store, region, condition, labels, parent_run_id, channel, pixel_size_um, region_id) -> int:

# After (merged)
def launch_viewer(store, fov, condition, channels=None, bio_rep=None) -> int | None:
def save_edited_labels(store, fov_info, fov, condition, labels, parent_run_id, channel, bio_rep=None) -> int:
```

#### 4. `viewer/_viewer.py` (no git conflict, manual update required)

Updated all internal functions:
- `_launch(region, condition)` -> `_launch(fov, condition, bio_rep=None)` — replaced `store.get_regions()` linear scan with `store._resolve_fov()`
- `_load_channel_layers(region, condition)` -> `_load_channel_layers(fov, condition, bio_rep=None)` — `store.read_image(fov, condition, ch.name, bio_rep=bio_rep)`
- `_load_label_layer(region, condition)` -> `_load_label_layer(fov, condition, bio_rep=None)` — `store.read_labels(fov, condition, bio_rep=bio_rep)`
- `save_edited_labels(region, condition, ..., pixel_size_um, region_id)` -> `save_edited_labels(fov_info, fov, condition, ..., bio_rep=None)` — FovInfo carries pixel_size_um and id

#### 5. `cli/view.py` (no git conflict, manual update required)

```python
# Before
@click.option("-r", "--region", required=True)
regions = store.get_regions()
run_id = launch_viewer(store, region, condition, channel_list)

# After
@click.option("-f", "--fov", required=True)
@click.option("--bio-rep", default=None)
fovs = store.get_fovs()
run_id = launch_viewer(store, fov, condition, channel_list, bio_rep=bio_rep)
```

#### 6. Test files (no git conflict, manual update required)

- `tests/test_segment/test_viewer.py`: All fixtures changed from `add_region("region_1", ...)` to `add_fov("fov_1", ...)`. All `save_edited_labels` calls updated to new signature with `fov_info` from `store._resolve_fov()`. `get_cells(region=...)` changed to `get_cells(fov=...)`.
- `tests/test_cli/test_view.py`: All CLI invocations changed from `-r region1` to `-f fov1`. `add_region` calls changed to `add_fov`. Help text assertions changed from `--region` to `--fov`.

### Verification

All 571 tests passed after conflict resolution.

## Key Insight

**Git conflict markers are necessary but not sufficient for merge safety.** In this case, git flagged 2 files but the semantic incompatibility spanned 6 files. The viewer module from the napari branch had never seen the FOV/bio_rep API, so every function signature and store call needed updating — but git saw no textual conflict because the viewer files were only modified by one branch.

**Always run the full test suite after multi-branch merges**, even when git reports a clean merge for some files.

## Prevention Strategies

### 1. Merge order matters

When merging parallel branches, **merge the broader/rename branch first**. The branch that makes sweeping terminology changes establishes the new baseline. Smaller feature branches then adapt to it. In this case, merging `feat/data-model-bio-rep-fov` first and then rebasing `feat/napari-viewer` onto it would have surfaced all viewer incompatibilities as rebase conflicts rather than silent runtime failures.

### 2. Keep shared primitives stable

The `store_labels_and_cells` function was independently modified by both branches (one made it private with a new signature, the other kept it public and used it). **Functions consumed by multiple modules should have their signatures locked at the branch point** or documented in an API contract.

### 3. Run full test suite on merge commits

Don't trust `git merge` status alone. Always run:

```bash
pytest tests/ -x -q  # Stop at first failure
```

Check specifically for:
- Test fixtures using old API names (`add_region` vs `add_fov`)
- Function calls with old parameter names
- CLI option names that no longer exist

### 4. Periodic rebasing during parallel development

For long-running parallel branches, weekly rebasing surfaces incompatibilities early:

```bash
git checkout feat/napari-viewer
git rebase origin/feat/data-model-bio-rep-fov
pytest tests/test_segment/test_viewer.py -v  # Quick check
```

## Related Documentation

- [Viewer module code review findings](../architecture-decisions/viewer-module-code-review-findings.md) — P1/P2/P3 findings from napari branch review
- [Viewer module P3 refactoring](../code-quality/viewer-module-p3-refactoring-and-cleanup.md) — YAGNI cleanup in viewer
- [Segment module private API encapsulation](../architecture-decisions/segment-module-private-api-encapsulation-fix.md) — hexagonal boundary enforcement
- [Core module P1 security fixes](../security-issues/core-module-p1-security-correctness-fixes.md) — `_validate_name()` patterns used for bio_rep
- [CLI-IO-Core integration bugs](./cli-io-core-integration-bugs.md) — prior integration testing patterns
- [Data model restructure plan](../../plans/2026-02-17-feat-data-model-bio-rep-fov-restructure-plan.md) — full plan for region->FOV rename + bio_rep
- [Napari viewer plan](../../plans/2026-02-16-feat-segment-module-3b-napari-viewer-plan.md) — original viewer implementation plan
- [Segment merge strategy plan](../../plans/2026-02-16-feat-next-work-phase-segment-merge-and-measure-plan.md) — branch merge ordering guidance

## Affected Files

| File | Change Type |
|------|------------|
| `src/percell3/cli/menu.py` | Git conflict resolved (kept both functions, updated viewer to FOV) |
| `src/percell3/segment/roi_import.py` | Git conflict resolved (4 regions: imports, signature, 2 call sites) |
| `src/percell3/segment/viewer/__init__.py` | Manual update (launch_viewer, save_edited_labels signatures) |
| `src/percell3/segment/viewer/_viewer.py` | Manual update (_launch, _load_channel_layers, _load_label_layer, save_edited_labels) |
| `src/percell3/cli/view.py` | Manual update (--region -> --fov, added --bio-rep) |
| `tests/test_segment/test_viewer.py` | Manual update (fixtures + all test cases) |
| `tests/test_cli/test_view.py` | Manual update (CLI invocations + fixtures) |
