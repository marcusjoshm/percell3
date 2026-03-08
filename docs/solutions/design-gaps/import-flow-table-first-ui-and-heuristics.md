---
title: "Import Flow Design Gaps — Auto-Detection Failures and Missing Table-First UI"
date: 2026-02-18
category: design-gaps
tags:
  - import-flow
  - file-group-assignment
  - condition-detection
  - hierarchy
  - user-experience
  - code-review
modules:
  - cli
  - io
severity: high
status: documented
problem_type:
  - missing-feature
  - brittle-heuristic
  - ux-hierarchy-mismatch
---

# Import Flow Design Gaps — Auto-Detection Failures and Missing Table-First UI

## Current Status (2026-03-08)

The table-first import UI has been **fully implemented**. All major design gaps identified in this document have been addressed:

- **Table-first file group assignment UI:** IMPLEMENTED. `_import_images()` in `menu.py` (line 1307) uses the table-first flow. It calls `build_file_groups()` and `show_file_group_table()` from `import_cmd.py` to display a numbered Rich table of file groups. Users can select groups and assign them to conditions with an interactive assignment loop.
- **`detect_conditions()` heuristic removed:** `io/conditions.py` no longer exists. The brittle suffix-pattern heuristic was removed entirely. Condition assignment is now fully manual via the table-first UI or automatic via `build_auto_assignments()` which derives conditions from file group tokens.
- **Global shape warning removed:** No `Inconsistent shapes` warning exists in `scanner.py`. Per-group shape info is shown in the file group table columns instead.
- **Per-group bio_rep support:** IMPLEMENTED. `ImportPlan` in `models.py` has `bio_rep_map: dict[str, str]` (line 163). `ImportEngine` uses it to assign per-group bio_reps (lines 140-143 of `engine.py`).
- **FileGroup dataclass:** IMPLEMENTED. Defined in `import_cmd.py` (line 291) with token, files, channels, z_slices, and shape fields.
- **Channel mapping and z-projection:** Integrated into the table-first flow in the menu's `_import_images()`.

**Remaining gaps from the original 6-phase plan:**
- Back-navigation ('b' returns to group selection): Implemented via the standard menu system.
- Single-group fast path: Present in the current implementation.

Found during real-world testing of the import flow with 96 TIFF files (8 conditions x 3 channels x 4 z-slices) after implementing the Condition > Bio Rep > FOV hierarchy restructuring.

## Problem Symptoms

User tested with actual microscopy data and encountered three blockers:

1. **Unhelpful "Inconsistent shapes" warning** — The scanner warns globally when different FOV groups have different image dimensions. This is normal in microscopy (different conditions at different magnifications, cropped ROIs) but appears as a scary warning.

2. **No interactive multi-group assignment UI** — After scanning 96 files into 8 file groups, the only option was a single "Condition name" text prompt. No way to see the file groups as a numbered table or assign different groups to different conditions.

3. **Bio rep prompted before condition context** — Bio rep is asked once globally before any condition is selected, but the hierarchy is Condition > Bio Rep > FOV, so bio rep should come after condition selection.

## Investigation Steps

### Step 1: Examined the import flow

`_import_images()` in `src/percell3/cli/menu.py:366-446` calls `detect_conditions()` from `src/percell3/io/conditions.py`. This heuristic relies on suffix pattern matching (`_s\d+$`, `_\d+$`, `_fov\d+$`, `_field\d+$`, `_site\d+$`).

Real filenames like `HS_+_dTAG13_Merged` don't match any suffix pattern. Detection returns `None`, and the user falls back to a single global condition name prompt.

### Step 2: Checked the brainstorm

The brainstorm (`docs/brainstorms/2026-02-18-io-redesign-metadata-assignment-brainstorm.md`, Decision 3) specifies a "Table-First File Group Assignment" workflow:

```
  #  File group              Ch  Z   Files
  1  30min_Recovery_Merged     3  4    12
  2  1hr_Recovery_Merged       3  4    12
  3  Untreated_Merged          3  4    12
```

- Select groups by space-separated numbers or `all`
- Assign condition (shows existing as pick list)
- Assign bio rep (shows existing for chosen condition)
- Table updates with assignments; `done` exits loop

This was never implemented. The plan's Phase 4 checkboxes are all unchecked.

### Step 3: Checked the scanner warning

`scanner.py:104-107` checks shape consistency across ALL files globally:

```python
shapes = {f.shape for f in discovered}
if len(shapes) > 1:
    warnings.append(f"Inconsistent shapes across files: {sorted(shapes)}")
```

This fires whenever any files have different dimensions — normal when importing multiple conditions.

### Step 4: Verified the engine infrastructure

`ImportPlan` in `src/percell3/io/models.py` already has `condition_map` and `fov_names` fields. `ImportEngine` can filter unassigned groups when `condition_map` is non-empty. The backend infrastructure exists; only the interactive assignment UI is missing.

## Root Cause Analysis

**Primary cause:** The implementation plan split schema restructuring (Phases 1-3) from UI implementation (Phase 4+). Phases 1-3 were completed (bio_reps table, condition-scoped bio reps, zarr path reversal). The table-first interactive UI described in the brainstorm's Decision 3 was documented in the plan but never coded — all Phase 4 checkboxes remain unchecked.

**Secondary cause:** The `detect_conditions()` heuristic is too narrow. It requires ALL FOV names to match one of five hardcoded suffix patterns AND have multiple distinct prefixes. Real-world microscopy names like `30min_Recovery_+_VCPi_Merged` and `HS_Merged` fail all patterns. When detection fails, users fall through to a single condition prompt with no alternative path.

**Tertiary cause:** The shape warning was designed as a data quality check but operates at the wrong granularity. Per-FOV-group consistency (same channel files have same dimensions) is meaningful. Cross-FOV-group differences are expected and normal.

## Working Solution

A 6-phase plan was created: `docs/plans/2026-02-18-feat-table-first-import-assignment-ui-plan.md`

### Phase 1: Remove global shape warning (scanner.py:104-107)

Delete the 4-line global check. Shape info moves to per-group columns in the file group table.

### Phase 2: Add file group table display (import_cmd.py)

Add `FileGroup` dataclass, `_build_file_groups()`, `_show_file_group_table()`, and `_next_fov_number()` helpers. Display a numbered Rich table with group name, channels, z-slices, file count, and shape per group.

### Phase 3: Rewrite `_import_images()` with assignment loop (menu.py)

Replace the entire function with the table-first flow:
1. Scan source and show file group table
2. Channel mapping (auto-match existing, prompt for new)
3. Z-projection selection
4. Assignment loop: select groups -> assign condition -> assign bio rep -> auto-number FOVs -> show updated table -> repeat until "done"
5. Assignment summary before confirmation
6. Execute import

Single-group fast path skips the loop.

### Phase 4: Per-group bio_rep support (models.py, engine.py)

Add `bio_rep_map: dict[str, str]` to `ImportPlan`. Engine uses per-group bio_rep when available.

### Phase 5: Back-navigation safety (menu.py)

'b' during assignment returns to group selection, not canceling the entire import.

### Phase 6: Tests

Scanner warning removal, assignment loop flows, FOV auto-numbering, bio_rep_map support.

### Code simplification opportunity

The code-simplicity review recommends removing `detect_conditions()` entirely (~221 LOC across `conditions.py`, `menu.py`, `import_cmd.py`, and tests). The table-first UI replaces it. The heuristic can be resurrected from git history if needed later.

## Key Code Locations

| Location | What | Status |
|----------|------|--------|
| `src/percell3/io/scanner.py:104-107` | Global shape warning | Remove |
| `src/percell3/cli/menu.py:366-446` | `_import_images()` | Rewrite |
| `src/percell3/cli/import_cmd.py:179-207` | `_show_preview()` flat table | Replace with file group table |
| `src/percell3/io/conditions.py` | `detect_conditions()` heuristic | Remove (~221 LOC) |
| `src/percell3/io/models.py` | `ImportPlan` dataclass | Add `bio_rep_map` field |
| `src/percell3/io/engine.py` | `ImportEngine.execute()` | Support per-group bio_rep |

## Prevention Strategies

### 1. Design-Implementation Synchronization

- **Write acceptance tests before implementation**: Tests that validate UI interactions (mock user inputs) serve as a living spec. If a model change breaks the flow, the test catches it.
- **Create "design contracts"** that are distinct from implementation plans: brainstorm = what to build, UI spec = exact interaction model, plan = code structure.
- **Check brainstorm checkboxes against code**: When marking plan items complete, verify the brainstorm decisions are satisfied, not just the mechanical code changes.

### 2. Real-World Data Testing

- Test with actual microscope filenames, not just synthetic `_ch00_s01` patterns.
- Key patterns to test: Leica exports (`30min_Recovery_+_VCPi_Merged_ch00_z00.tif`), Zeiss Scene naming, generic high-throughput plate naming.
- Include 96+ file test cases to validate pagination and performance.

### 3. Scanner Warning Granularity

- Warnings about metadata consistency should operate at the right level: per-FOV-group for shapes, global for pixel sizes.
- False-alarm warnings train users to ignore all warnings, undermining genuinely useful ones.

### Code Review Checklist

When reviewing import-related changes:

- [ ] File groups displayed as numbered table (not flat comma-separated list)
- [ ] User can select groups by number and assign to different conditions
- [ ] Bio rep prompted after condition selection, not before
- [ ] FOV auto-numbering is per (condition, bio_rep) scope
- [ ] Single-group fast path exists (no forced multi-select loop)
- [ ] 'b' returns to group selection, not canceling entire import
- [ ] No global shape warning across all files
- [ ] Existing conditions shown as pick list for incremental imports
- [ ] All tests pass with real-world filename patterns

## Related Documentation

### Solution Documents

- `/Users/leelab/percell3/docs/solutions/architecture-decisions/cli-module-code-review-findings.md` — Menu-as-thin-dispatcher pattern; import flow should delegate to shared functions
- `/Users/leelab/percell3/docs/solutions/integration-issues/cli-io-dual-mode-review-fixes.md` — Double-scan prevention (pass `scan_result` to `_run_import`), variable shadowing, CLI/menu parity
- `/Users/leelab/percell3/docs/solutions/integration-issues/cli-io-core-integration-bugs.md` — Channel registration bug for plain TIFFs without `_ch00` suffix
- `/Users/leelab/percell3/docs/solutions/integration-issues/napari-viewer-datamodel-merge-api-conflicts.md` — Cascade of API changes when data model changes; run full test suite after merges

### Brainstorm Documents

- `/Users/leelab/percell3/docs/brainstorms/2026-02-18-io-redesign-metadata-assignment-brainstorm.md` — **THE UNIMPLEMENTED DESIGN**: table-first interactive approach, Condition > Bio Rep > FOV hierarchy, context-aware prompts
- `/Users/leelab/percell3/docs/brainstorms/2026-02-17-data-model-bio-rep-fov-restructure-brainstorm.md` — Bio Rep > Condition > FOV hierarchy (superseded by 2026-02-18 brainstorm for Condition > Bio Rep > FOV)
- `/Users/leelab/percell3/docs/brainstorms/2026-02-17-cli-ux-improvements-brainstorm.md` — Numbered selection system (Feature #3) is prerequisite for table-first UI

### Plan Document

- `/Users/leelab/percell3/docs/plans/2026-02-18-feat-table-first-import-assignment-ui-plan.md` — Full 6-phase implementation plan with pseudocode and acceptance criteria
