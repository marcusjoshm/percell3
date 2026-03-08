---
title: "Menu UI Two-Tier Redesign"
type: feat
date: 2026-02-23
---

# Menu UI Two-Tier Redesign

## Overview

Restructure the PerCell 3 interactive menu from a flat 13-item list into a two-tier grouped menu with 7 functional categories, screen clearing between transitions, "Press Enter to continue" gates, and a reusable `Menu` class architecture. Based on the [menu UI redesign brainstorm](../brainstorms/2026-02-20-menu-ui-redesign-brainstorm.md).

## Problem Statement

1. **Flat menu with 13 items** -- overwhelming, hard to scan, no logical grouping
2. **No screen clearing** -- banner reprints into scrollback every loop iteration
3. **Ad-hoc sub-menus** -- Query, Edit, Measure, Workflow sub-menus use inline `console.print` instead of a reusable structure
4. **No pause after actions** -- output (tables, success/error messages) is immediately overwritten by the next menu redraw
5. **No item descriptions** -- menu items show only a label, no hint about what each one does

## Design Decisions

### Q: `q` semantics in sub-menus?
Keep current behavior: `q` in sub-prompts means "cancel/back" (same as `b`), `q` at the Main Menu prompt means "exit application." Remove `q=quit` from sub-menu prompt hints to avoid confusion. Hint becomes `(h=home, b=back)` in sub-menus, Main Menu prompt has no nav hints (just `q=quit`).

### Q: How does `Menu.run()` interact with `_MenuCancel` / `_MenuHome`?
`Menu.run()` catches `_MenuCancel` and returns to the parent caller. `_MenuHome` propagates all the way up to `run_interactive_menu()`, which catches it and redraws the Main Menu (same as today).

### Q: "Press Enter" after errors?
Yes. The gate appears after ALL handler exits -- success, error, and cancellation. This ensures users always see the output before screen clear.

### Q: `console.clear()` in tests?
Guard with `if console.is_terminal:` before calling `console.clear()`. CliRunner tests use piped input (not a real TTY), so `is_terminal` is False and clear is skipped. No test changes needed for the clear itself.

### Q: Banner on sub-menus?
Compact header on sub-menus. Full ASCII art banner on Main Menu only. Sub-menus show a one-line header: `PerCell 3 | Experiment: <name>` plus the sub-menu title (e.g., `DATA MENU`). This avoids eating 11 lines of terminal space on every sub-menu.

### Q: Convert looping handlers to Menu instances?
- **`_query_experiment`** -- Yes, becomes a proper 3rd-tier Query Menu (already has 5 numbered options)
- **`_edit_experiment`** -- Yes, becomes a proper 3rd-tier Edit Menu (already has 5 numbered options)
- **`_run_workflow`** -- Yes, becomes a proper Workflows Menu (has 2 options)
- **`_measure_channels`** -- No. The mode selection is part of a single measurement flow, not a persistent menu. Keep as a looping handler under Analyze.

### Q: Interactive pagination?
Defer to a follow-up task. Keep `page_size=20` truncation for now.

## Menu Tree

```
MAIN MENU
  1. Setup       - Create and select experiments
  2. Import      - Import LIF, TIFF, or CZI images
  3. Segment     - Single-cell segmentation with Cellpose
  4. Analyze     - Measure, threshold, and analyze cells
  5. View        - View images and masks in napari
  6. Data        - Query, edit, and export experiment data
  7. Workflows   - Run automated analysis pipelines
  8. Plugins     - Extend functionality with plugins  (coming soon)
  q. Exit

SETUP MENU
  1. Create experiment     - Create a new .percell experiment
  2. Select experiment     - Open an existing experiment
  3. Back

IMPORT MENU
  1. Import images         - Load LIF, TIFF, or CZI files
  2. Back

SEGMENT MENU
  1. Segment cells         - Run Cellpose segmentation
  2. Back

ANALYZE MENU
  1. Measure channels      - Measure fluorescence intensities per cell
  2. Apply threshold       - Otsu thresholding and particle detection
  3. Back

VIEW MENU
  1. View in napari        - Open images and masks in napari viewer
  2. Back

DATA MENU
  1. Query experiment      - Inspect experiment data
  2. Edit experiment       - Rename conditions, FOVs, channels, bio-reps
  3. Export to CSV          - Export measurements and particle data
  4. Back

  QUERY MENU (3rd tier under Data > Query)
    1. Experiment summary    - Per-FOV overview of cells and measurements
    2. Channels              - List channels in the experiment
    3. FOVs                  - List fields of view
    4. Conditions            - List experimental conditions
    5. Biological replicates - List biological replicates
    6. Back

  EDIT MENU (3rd tier under Data > Edit)
    1. Rename experiment     - Change the experiment name
    2. Rename condition      - Rename a condition
    3. Rename FOV            - Rename a field of view
    4. Rename channel        - Rename a channel
    5. Rename bio-rep        - Rename a biological replicate
    6. Back

WORKFLOWS MENU
  1. Run workflow           - Run automated analysis pipelines  (coming soon)
  2. Back
```

## Item Format

Rich markup for each item:

```
  [bold white]1.[/bold white] [bold yellow]Setup[/bold yellow]       [dim]- Create and select experiments[/dim]
```

Disabled items:

```
  [bold white]8.[/bold white] [dim]Plugins     - Extend functionality with plugins  (coming soon)[/dim]
```

"Back" items:

```
  [bold white]3.[/bold white] [red]Back[/red]
```

## Architecture

### New file: `src/percell3/cli/menu_system.py`

Contains the reusable `Menu`, `SubMenu`, `MenuItem` classes. Keeps `menu.py` for handler functions and the `run_interactive_menu()` entry point.

### `MenuItem` dataclass

```python
@dataclass(frozen=True)
class MenuItem:
    key: str                                        # "1", "2", ..., "q"
    label: str                                      # "Setup", "Import", ...
    description: str                                # "Create and select experiments"
    handler: Callable[[MenuState], None] | None     # handler function or None
    enabled: bool = True                            # False for "coming soon"
```

### `Menu` class

```python
class Menu:
    def __init__(
        self,
        title: str,                    # "MAIN MENU", "SETUP MENU", etc.
        items: list[MenuItem],         # menu items (last one is typically "Back")
        state: MenuState,              # shared session state
        show_banner: bool = False,     # True only for main menu
    ) -> None: ...

    def run(self) -> None:
        """Render-prompt-dispatch loop.

        - Clears screen (if TTY)
        - Renders header (banner or compact) + experiment context + title
        - Renders items in styled format
        - Prompts for selection
        - Dispatches to handler
        - Shows "Press Enter to continue..." gate after handler returns
        - Loops until Back/_MenuCancel exits, or _MenuHome propagates up
        """
```

### `Menu.run()` pseudocode

```
def run(self):
    while True:
        _clear_screen()
        _render_header()
        _render_items()

        try:
            choice = _prompt()                # raises _MenuCancel on 'b', _MenuHome on 'h'
        except _MenuCancel:
            return                            # back to parent

        item = _find_item(choice)
        if item is None:
            continue                          # invalid input
        if not item.enabled:
            print("not yet available")
            _wait_for_enter()
            continue
        if item.handler is None:
            return                            # "Back" item (handler=None)

        try:
            item.handler(self.state)
        except _MenuCancel:
            pass                              # action cancelled, stay in this menu
        except _MenuHome:
            raise                             # propagate to main menu
        except ExperimentError as e:
            print(f"Error: {e}")
        except Exception as e:
            print(f"Internal error: {e}")

        _wait_for_enter()                     # "Press Enter to continue..."
```

### Screen clearing

```python
def _clear_screen(self) -> None:
    if console.is_terminal:
        console.clear()
```

### "Press Enter to continue" gate

```python
def _wait_for_enter(self) -> None:
    if console.is_terminal:
        console.input("\n[dim]Press Enter to continue...[/dim]")
```

### Header rendering

**Main Menu** (`show_banner=True`): full ASCII art banner + tagline + experiment context + "MAIN MENU" title.

**Sub-menus** (`show_banner=False`): compact one-liner + title.

```
PerCell 3 | Experiment: percell3_test_6
DATA MENU

  1. Query experiment      - Inspect experiment data
  2. Edit experiment       - Rename conditions, FOVs, channels, bio-reps
  3. Export to CSV          - Export measurements and particle data
  4. Back
```

## Implementation Phases

### Phase 1: Create `menu_system.py` with `Menu` and `MenuItem`

**Files:**
- Create `src/percell3/cli/menu_system.py`
- Create `tests/test_cli/test_menu_system.py`

**Tasks:**
- [ ] Define `MenuItem` dataclass with `key`, `label`, `description`, `handler`, `enabled`
- [ ] Implement `Menu` class with `run()`, `_clear_screen()`, `_wait_for_enter()`, `_render_header()`, `_render_items()`, `_prompt()`
- [ ] `_prompt()` uses `menu_prompt()` from existing code for sub-menus; Main Menu uses a simplified prompt without `h`/`b` hints (only shows `q=quit`)
- [ ] `_clear_screen()` gated on `console.is_terminal`
- [ ] `_wait_for_enter()` gated on `console.is_terminal`
- [ ] Unit tests for `Menu.run()` with mocked `console.input` -- verify dispatch, back navigation, home propagation, disabled item handling, error handling, screen clear skipping in non-TTY

### Phase 2: Build the menu tree and rewire `run_interactive_menu()`

**Files:**
- Modify `src/percell3/cli/menu.py`

**Tasks:**
- [ ] Build main menu items as `MenuItem` instances with category handlers
- [ ] Build sub-menu items for each category (Setup, Import, Segment, Analyze, View, Data, Workflows)
- [ ] Each category handler creates a `Menu` and calls `menu.run()`
- [ ] "Back" items use `handler=None` (Menu.run returns when handler is None)
- [ ] Replace `run_interactive_menu()` to use `Menu(show_banner=True).run()` for the main loop
- [ ] Keep `_try_auto_load()` before the main menu loop
- [ ] Keep `state.close()` in the `finally` block
- [ ] Preserve `KeyboardInterrupt` handling (add `except KeyboardInterrupt: break` to the main loop)

### Phase 3: Convert `_query_experiment` and `_edit_experiment` to Menu instances

**Files:**
- Modify `src/percell3/cli/menu.py`

**Tasks:**
- [ ] Extract each `_query_experiment` branch (channels, FOVs, conditions, bio-reps, summary) into a standalone handler function (e.g., `_query_channels(state)`, `_query_fovs(state)`, etc.)
- [ ] Build a Query Menu with 5 items + Back, launched from Data > Query
- [ ] Extract each `_edit_experiment` branch into a standalone handler (e.g., `_rename_condition(state)`, `_rename_channel(state)`, etc.)
- [ ] Build an Edit Menu with 5 items + Back, launched from Data > Edit
- [ ] Remove the `while True` loops from these handlers -- the `Menu.run()` loop replaces them
- [ ] The "Press Enter to continue" gate now happens in `Menu.run()` after each handler returns

### Phase 4: Adapt remaining handlers

**Files:**
- Modify `src/percell3/cli/menu.py`

**Tasks:**
- [ ] `_measure_channels`: keep internal `while True` loop for mode selection (it is a single-flow handler, not a menu). The Analyze Menu's `_wait_for_enter()` runs after `_measure_channels` returns
- [ ] `_apply_threshold`: no structural changes. The threshold flow interleaves napari and console output. The Analyze Menu's gate runs after the entire flow completes
- [ ] `_segment_cells`: no structural changes. Auto-measure runs inline. Gate runs after the full handler completes
- [ ] `_import_images`: no structural changes
- [ ] `_run_workflow`: convert the `while True` loop into a Workflows Menu with "Run workflow" as the single enabled item. The stub message shows and the gate runs
- [ ] `_export_csv`: no structural changes. Launched from Data > Export
- [ ] `_view_napari`: no structural changes. napari blocks the terminal; gate runs after viewer closes

### Phase 5: Update tests

**Files:**
- Modify `tests/test_cli/test_menu.py`
- Create `tests/test_cli/test_menu_system.py` (if not done in Phase 1)
- Modify `tests/test_cli/test_menu_import.py` (import paths)
- Modify `tests/test_cli/test_menu_segment.py` (import paths)

**Tasks:**
- [ ] Update imports in test files for any moved/renamed private functions
- [ ] Update `_invoke_menu` helper in `test_menu.py` to account for the new input sequence (Main Menu → category number → sub-menu number → action inputs → Enter to continue → back/quit)
- [ ] Add integration tests: Main Menu → Setup → Create → verify loops back to Setup → Back → verify at Main Menu
- [ ] Add integration test: Main Menu → Data → Query → Channels → verify gate → Back → Back → verify at Main Menu
- [ ] Add integration test: `h` from 3rd-tier Query menu returns to Main Menu
- [ ] Add integration test: `b` from 3rd-tier Query menu returns to Data Menu
- [ ] Verify all 164 existing CLI tests pass (some will need input sequence adjustments)

### Phase 6: Table display improvements

**Files:**
- Modify `src/percell3/cli/import_cmd.py` (`show_file_group_table`)
- Modify `src/percell3/cli/menu.py` (`_show_fov_status_table`)
- Modify `src/percell3/cli/query.py` (`format_output`)

**Tasks:**
- [ ] Add `max_width` and `overflow="ellipsis"` to long-text columns (fov name, condition name) in all Rich Table constructors
- [ ] Add pager support: if table row count >= 30 and `console.is_terminal`, use `with console.pager(styles=True):`
- [ ] Defer interactive pagination of `_print_numbered_list` to a follow-up task

## Acceptance Criteria

- [ ] Main Menu shows 7 functional categories + Plugins (disabled) + Exit, with `number. Title - description` format
- [ ] Selecting a category opens a sub-menu with relevant items + "Back"
- [ ] Screen clears between menu transitions (in TTY mode only)
- [ ] "Press Enter to continue..." appears after every handler completes (success, error, or cancel)
- [ ] `h` from any depth returns to Main Menu
- [ ] `b` from any depth returns one level up
- [ ] Selecting "Back" item returns one level up (same as `b`)
- [ ] `q` at Main Menu exits the application
- [ ] `q` in sub-prompts acts as cancel/back (not application exit)
- [ ] Full ASCII banner shown only on Main Menu; sub-menus show compact header
- [ ] Query and Edit are proper 3rd-tier menus under Data
- [ ] Disabled items show "(coming soon)" in dim text and show a message when selected
- [ ] All 164+ existing CLI tests pass
- [ ] `percell3 --help` still completes in < 500ms (no new eager imports)
- [ ] Tables with 30+ rows auto-page through system pager (in TTY mode)

## Files Changed

| File | Change |
|------|--------|
| `src/percell3/cli/menu_system.py` | **New** -- `Menu`, `MenuItem` classes |
| `src/percell3/cli/menu.py` | Rewire to use `Menu` class; extract query/edit branch handlers; remove inline sub-menus |
| `src/percell3/cli/import_cmd.py` | Add `max_width`/`overflow` to table columns |
| `src/percell3/cli/query.py` | Add `max_width`/`overflow` + pager support to `format_output()` |
| `tests/test_cli/test_menu_system.py` | **New** -- unit tests for `Menu` class |
| `tests/test_cli/test_menu.py` | Update input sequences and imports for new menu structure |
| `tests/test_cli/test_menu_import.py` | Update imports if any private names moved |
| `tests/test_cli/test_menu_segment.py` | Update imports if any private names moved |

## Risks

1. **Test churn** -- most existing menu tests feed input as `"8\n4\n..."` which maps to the current flat menu. The new two-tier structure changes the navigation sequence. Mitigation: update tests in Phase 5 as a dedicated task.
2. **Pager in CI** -- `console.pager()` opens the system pager (`less`), which hangs in non-interactive CI. Mitigation: gate on `console.is_terminal`.
3. **napari + screen clear** -- the threshold handler interleaves napari and console output. Screen clearing mid-flow would destroy feedback. Mitigation: screen clear only happens in `Menu.run()`, not inside handlers. Handlers print freely.

## References

- Brainstorm: `docs/brainstorms/2026-02-20-menu-ui-redesign-brainstorm.md`
- CLI code review findings: `docs/solutions/architecture-decisions/cli-module-code-review-findings.md`
- Import flow UI pattern: `docs/solutions/design-gaps/import-flow-table-first-ui-and-heuristics.md`
- Current menu implementation: `src/percell3/cli/menu.py`
