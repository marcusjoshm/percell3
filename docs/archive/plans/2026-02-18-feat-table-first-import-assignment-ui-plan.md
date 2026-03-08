---
title: "feat: Table-First Import Assignment UI"
type: feat
date: 2026-02-18
---

# Table-First Import Assignment UI

## Overview

Redesign `_import_images()` in `menu.py` to use the **table-first interactive approach** described in the brainstorm (`docs/brainstorms/2026-02-18-io-redesign-metadata-assignment-brainstorm.md`). The current import flow fails on real-world data because it depends on condition auto-detection heuristics that don't match common microscopy naming patterns, and offers no way to manually assign file groups to different conditions.

## Problem Statement

User tested with 96 TIFF files (8 conditions x 3 channels x 4 z-slices). Three problems:

1. **Unhelpful "Inconsistent shapes" warning** — Different conditions have different image sizes. This is normal in microscopy but the scanner warns globally across all files.
2. **No interactive assignment UI** — After auto-detection fails, only a single "Condition name" prompt appears. No way to assign different file groups to different conditions.
3. **Bio rep prompted before condition context** — Bio rep is asked once globally before any condition is selected, but the hierarchy is Condition > Bio Rep > FOV.

## Files to Modify

| File | Changes |
|------|---------|
| `src/percell3/io/scanner.py` | Remove global shape warning; move shape info to per-file-group display |
| `src/percell3/cli/menu.py` | Replace `_import_images()` with table-first assignment flow |
| `src/percell3/cli/import_cmd.py` | Update `_show_preview()` to display file group table; add `_next_fov_number()` helper |
| `tests/test_cli/test_menu_import.py` | Tests for the new interactive assignment flow |
| `tests/test_io/test_scanner.py` | Update tests for removed global shape warning |

## Implementation

### Phase 1: Remove global shape warning from scanner

**File: `src/percell3/io/scanner.py`** (lines 104-107)

- [x] Remove the global shape consistency check that fires when shapes differ across all files
- [x] Keep the pixel size inconsistency warning (that one is useful)
- [x] Shape info will be displayed per-file-group in the new table instead

```python
# DELETE lines 104-107:
# shapes = {f.shape for f in discovered}
# if len(shapes) > 1:
#     warnings.append(f"Inconsistent shapes across files: {sorted(shapes)}")
```

### Phase 2: Add file group table display

**File: `src/percell3/cli/import_cmd.py`**

- [x] Add `_build_file_groups()` helper that groups `ScanResult.files` by FOV token and returns a list of `FileGroup` dataclass instances
- [x] Add `_show_file_group_table()` that displays a Rich numbered table:

```
  #  File group                       Ch  Z   Files  Shape
  1  30min_Recovery_+_VCPi_Merged      3  4    12    3246 x 3256
  2  30min_Recovery_+_dTAG13_Merged    3  4    12    2804 x 2791
  3  HS_Merged                         3  4    12    3251 x 3235
  ...
```

- [x] Add `_next_fov_number()` helper that queries existing FOVs in a (condition, bio_rep) scope and returns the next number
- [x] Update `_show_preview()` to call `_show_file_group_table()` instead of showing FOVs as a comma-separated list

```python
@dataclass
class FileGroup:
    """A group of files sharing the same FOV token."""
    token: str          # e.g. "30min_Recovery_+_VCPi_Merged"
    files: list[DiscoveredFile]
    channels: list[str]
    z_slices: list[str]
    shape: tuple[int, int]

def _build_file_groups(scan_result: ScanResult) -> list[FileGroup]:
    """Group discovered files by FOV token."""
    ...

def _show_file_group_table(groups: list[FileGroup], assignments: dict[str, tuple[str, str, str]] | None = None) -> None:
    """Display numbered table of file groups with optional assignment info."""
    ...

def _next_fov_number(store: ExperimentStore, condition: str, bio_rep: str) -> int:
    """Return next FOV number for the given (condition, bio_rep) scope."""
    existing = store.get_fovs(condition=condition, bio_rep=bio_rep)
    return len(existing) + 1
```

### Phase 3: Rewrite `_import_images()` with assignment loop

**File: `src/percell3/cli/menu.py`** (lines 366-446)

- [x] Replace the entire `_import_images()` function with the table-first flow
- [x] Add `_prompt_condition_for_assignment()` helper: shows existing conditions + "(new condition)" option
- [x] Add `_prompt_bio_rep_for_assignment()` helper: shows existing bio reps for chosen condition + "(new)" option
- [x] Add `_show_assignment_summary()` helper: displays final assignments before confirmation

**New flow:**

```
1. Scan source → show file group table
2. Channel mapping (auto-match existing, prompt for new)
3. Z-projection selection (if z-slices detected)
4. Assignment loop:
   a. Show unassigned file groups (numbered)
   b. User selects groups (space-separated numbers or "all")
   c. Prompt condition name (pick from existing or type new)
   d. Prompt bio rep (default N1, pick from existing for chosen condition)
   e. Auto-number FOVs within (condition, bio_rep) scope
   f. Mark groups as assigned
   g. Show updated table with assignments
   h. Repeat until "done" or all assigned
5. Show assignment summary
6. Confirm and execute import
```

**Single-group fast path:** If only one file group exists, skip the assignment loop — prompt directly for condition and bio rep.

**Detailed pseudocode:**

```python
def _import_images(state: MenuState) -> None:
    store = state.require_experiment()

    # 1. Get source and scan
    source_str, source_files = _prompt_source_path()
    scanner = FileScanner()
    scan_result = scanner.scan(source, files=source_files)

    # 2. Build and display file groups
    groups = _build_file_groups(scan_result)
    if not groups:
        console.print("[red]No file groups found.[/red]")
        return
    _show_file_group_table(groups)

    # 3. Channel mapping
    channel_maps = _prompt_channel_mapping(scan_result, store)

    # 4. Z-projection
    z_method = _prompt_z_projection(scan_result)

    # 5. Assignment loop
    condition_map = {}   # fov_token -> condition_name
    fov_names = {}       # fov_token -> "FOV_001"
    bio_rep_map = {}     # fov_token -> bio_rep_name
    assigned = set()     # indices of assigned groups

    if len(groups) == 1:
        # Single-group fast path
        condition = _prompt_condition_for_assignment(store)
        bio_rep = _prompt_bio_rep_for_assignment(store, condition)
        next_num = _next_fov_number(store, condition, bio_rep)
        g = groups[0]
        condition_map[g.token] = condition
        fov_names[g.token] = f"FOV_{next_num:03d}"
        bio_rep_map[g.token] = bio_rep
    else:
        while len(assigned) < len(groups):
            # Show unassigned groups
            unassigned = [(i, g) for i, g in enumerate(groups) if i not in assigned]
            console.print(f"\nUnassigned file groups ({len(unassigned)} remaining):")
            _show_unassigned_groups(unassigned)

            # Select groups
            selection = menu_prompt("Select groups (numbers, 'all', or 'done')")
            if selection.lower() == "done":
                break
            selected_indices = _parse_group_selection(selection, unassigned)

            # Assign condition
            condition = _prompt_condition_for_assignment(store)

            # Assign bio rep
            bio_rep = _prompt_bio_rep_for_assignment(store, condition)

            # Auto-number FOVs
            existing_in_scope = _next_fov_number(store, condition, bio_rep)
            already_assigned = sum(1 for t, c in condition_map.items()
                                   if c == condition and bio_rep_map.get(t) == bio_rep)
            base_num = existing_in_scope + already_assigned

            for offset, idx in enumerate(selected_indices):
                g = groups[idx]
                condition_map[g.token] = condition
                fov_names[g.token] = f"FOV_{base_num + offset:03d}"
                bio_rep_map[g.token] = bio_rep
                assigned.add(idx)

            # Show updated table
            _show_file_group_table(groups, assignments=...)

    if not condition_map:
        console.print("[yellow]No groups assigned. Import cancelled.[/yellow]")
        return

    # 6. Show summary and confirm
    _show_assignment_summary(condition_map, fov_names, bio_rep_map, groups)
    if numbered_select_one(["Yes", "No"], "Proceed with import?") != "Yes":
        return

    # 7. Execute import
    # Pick a representative bio_rep for the ImportPlan (engine uses condition_map)
    default_bio_rep = next(iter(bio_rep_map.values()), "N1")
    _run_import(store, source, "default", channel_maps, z_method,
                yes=True, bio_rep=default_bio_rep,
                condition_map=condition_map, fov_names=fov_names,
                source_files=source_files, scan_result=scan_result)
```

### Phase 4: Update ImportEngine to support per-group bio_rep

**File: `src/percell3/io/models.py`**

- [x] Add `bio_rep_map: dict[str, str]` field to `ImportPlan` (maps fov_token -> bio_rep name, default empty)

**File: `src/percell3/io/engine.py`**

- [x] When `bio_rep_map` is present, use per-group bio_rep instead of the plan-level `bio_rep`
- [x] Filter out unassigned groups when `condition_map` is non-empty (skip groups not in `condition_map`)

```python
# In the FOV loop:
if plan.condition_map and fov_token not in plan.condition_map:
    skipped += 1
    continue

# Bio rep per group:
if plan.bio_rep_map and fov_token in plan.bio_rep_map:
    bio_rep = sanitize_name(plan.bio_rep_map[fov_token])
else:
    bio_rep = sanitize_name(plan.bio_rep)
```

### Phase 5: Back-navigation safety in assignment loop

- [x] Wrap condition and bio rep prompts in `try/except _MenuCancel` so 'b' returns to group selection instead of canceling the entire import
- [x] 'h' (home) still cancels the entire import as expected

### Phase 6: Update tests

- [x] `tests/test_io/test_scanner.py`: Remove test expectations for global shape warning
- [x] `tests/test_cli/test_menu_import.py`: Add tests for:
  - Single-group fast path
  - Multi-group assignment loop (assign 3 groups to 2 conditions)
  - "done" exits early, unassigned groups skipped
  - FOV auto-numbering continues from existing
  - 'b' during condition prompt returns to group selection (not cancel)
- [x] `tests/test_io/test_engine.py`: Add test for `bio_rep_map` support

## Acceptance Criteria

- [ ] Importing 96 files with 8 distinct file groups shows a numbered table with shape/channel info per group
- [ ] No "Inconsistent shapes" warning when different groups have different sizes
- [ ] User can select groups by number and assign to different conditions
- [ ] FOVs are auto-numbered FOV_001, FOV_002... per (condition, bio_rep) scope
- [ ] Bio rep is prompted after condition selection, not before
- [ ] Single file group skips the multi-select loop
- [ ] Assignment summary shows all mappings before confirmation
- [ ] 'done' exits the assignment loop, importing only assigned groups
- [ ] Pressing 'b' during assignment returns to group selection, not canceling
- [ ] All existing tests pass

## Edge Cases

- **Single file group**: Skip assignment loop, prompt condition + bio rep directly
- **All groups same condition**: User types "all", then one condition + bio rep
- **96+ file groups**: Table uses pagination (show all groups since user needs to see them for assignment)
- **Re-assign to same condition twice**: FOV numbering increments correctly across rounds
- **Existing experiment with data**: Condition pick list shows existing + "(new condition)"
- **Empty experiment**: No pick list, just text prompt for condition name

## References

- Brainstorm: `docs/brainstorms/2026-02-18-io-redesign-metadata-assignment-brainstorm.md`
- Current import flow: `src/percell3/cli/menu.py:366-446`
- Scanner shape warning: `src/percell3/io/scanner.py:104-107`
- File group table: `src/percell3/cli/import_cmd.py:179-207`
- Condition auto-detection: `src/percell3/io/conditions.py`
- CellProfiler IO research: Background agent findings on table-first approach
