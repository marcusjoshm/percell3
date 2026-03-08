---
title: "PerCell 3 Menu UI Redesign — Multi-Tier Menus with PerCell 1 Style"
type: feat
date: 2026-02-20
---

# PerCell 3 Menu UI Redesign

## What We're Building

A two-tier menu system for PerCell 3 that matches the visual style and navigational clarity of the original PerCell, but without the strict 80x24 terminal constraint. The new UI will:

- Clear the screen between menu transitions (page-like feel)
- Use 7 main menu categories, each opening a sub-menu
- Display items as `number. Colored Title - dim description`
- Auto-page large tables through the system pager
- Use a reusable `Menu` class architecture (Approach A)

## Why This Approach

### Problems with the current PerCell 3 UI
1. **Flat menu with 13 items** — overwhelming, hard to scan, no logical grouping
2. **No screen clearing** — banner reprints endlessly in scrollback, creating visual clutter
3. **Ad-hoc sub-menus** — Query, Edit, Export sub-menus use inline `console.print` instead of the `MenuItem` dataclass, causing inconsistent behavior
4. **Tables overflow** — Rich tables have no `max_width` constraints or pagination, so wide/tall tables break the layout
5. **Numbered list truncation** — `page_size=20` cuts off with "and N more" but provides no way to browse remaining items

### Why not a TUI framework (Textual, curses, etc.)?
- PerCell 3 is a **sequential workflow tool** (pick → configure → run → view results → go back). Textual's async event-driven model adds complexity without proportional UX gain.
- Textual introduces async (`asyncio`) which conflicts with synchronous CPU-bound operations (Cellpose, scipy).
- napari (Qt) coexistence is cleaner with simple `input()` loops than with a persistent TUI event loop.
- Rich already provides everything needed: styled tables, progress bars, markup formatting, console pager.
- The current `menu_prompt()` / `numbered_select_one()` pattern is trivially testable; TUI testing requires specialized frameworks.

### Why reusable Menu classes (Approach A)?
- The original PerCell uses `Menu`/`MenuItem`/`MenuFactory` classes successfully — proven pattern
- Avoids the ad-hoc sub-menu inconsistency in the current code
- Adding/removing menu items becomes declarative rather than scattered `console.print` calls
- Screen clearing, navigation shortcuts, and item formatting happen in one place

## Key Decisions

### 1. Screen Clearing
- `console.clear()` before every menu redraw
- After action completion: "Press Enter to continue..." gate before clearing
- Users can read output (tables, success messages, errors) before returning to menu

### 2. Menu Structure — 7 Categories + Exit

```
MAIN MENU:
  1. Setup       - Create and select experiments
  2. Import      - Import LIF, TIFF, or CZI images
  3. Segment     - Single-cell segmentation with Cellpose
  4. Analyze     - Measure, threshold, and analyze cells
  5. View        - View images and masks in napari
  6. Data        - Query, edit, and export experiment data
  7. Workflows   - Run automated analysis pipelines
  8. Exit

SETUP MENU:
  1. Create experiment     - Create a new .percell experiment
  2. Select experiment     - Open an existing experiment
  3. Back to Main Menu

IMPORT MENU:
  1. Import images         - Load LIF, TIFF, or CZI files
  2. Back to Main Menu

SEGMENT MENU:
  1. Segment cells         - Run Cellpose segmentation
  2. Back to Main Menu

ANALYZE MENU:
  1. Measure channels      - Measure fluorescence intensities per cell
  2. Apply threshold       - Otsu thresholding and particle detection
  3. Back to Main Menu

VIEW MENU:
  1. View in napari        - Open images and masks in napari viewer
  2. Back to Main Menu

DATA MENU:
  1. Query experiment      - Inspect channels, FOVs, conditions, summary
  2. Edit experiment       - Rename conditions, FOVs, channels, bio-reps
  3. Export to CSV          - Export measurements and particle data
  4. Back to Main Menu

WORKFLOWS MENU:
  1. Run workflow           - Run automated analysis pipelines
  2. Back to Main Menu
```

### 3. Item Format
Hybrid style with Rich markup:
- Number is **bold white**: `[bold white]1.[/bold white]`
- Title is **bold yellow**: `[bold yellow]Setup[/bold yellow]`
- Description is **dim**: `[dim]- Create and select experiments[/dim]`
- "Back to Main Menu" uses **red**: `[red]Back to Main Menu[/red]`

### 4. Navigation
- Every sub-menu ends with a numbered "Back to Main Menu" item
- Prompt shows hints: `Select an option (h=home, b=back, q=quit):`
- `h` = jump to main menu from anywhere (existing `_MenuHome` exception)
- `b` = go back one level (existing `_MenuCancel` exception)
- `q` = quit the application
- Main menu prompt: `Select an option (1-8):`

### 5. Table Display
- Small tables (< 30 rows): print directly with `console.print(table)`
- Large tables (30+ rows): auto-pipe through `console.pager(styles=True)`
- All table columns get `max_width` constraints and `overflow="ellipsis"` to prevent horizontal overflow
- Existing `_print_numbered_list()` page_size=20 truncation gets replaced with interactive pagination (Enter = next page, or type number to select)

### 6. Header/Banner
- Keep the current microscope + PERCELL ASCII art banner with cyan/green/magenta coloring
- Show "PerCell 3.0 — Single-Cell Microscopy Analysis" tagline
- Show current experiment context below banner
- Menu title (e.g., "MAIN MENU:", "ANALYZE MENU:") appears below experiment context
- Banner + context + title is rendered by the `Menu` class, not by each handler

### 7. Architecture
Build a reusable `Menu` class in `menu.py` (or extract to `menu_system.py`) with:
- `MenuItem` dataclass: `key`, `label`, `description`, `handler`, `enabled`, `color`
- `Menu` class: holds title + list of `MenuItem`, renders with screen clear + banner + items + prompt
- `SubMenu(Menu)`: adds "Back to Main Menu" item automatically
- `MainMenu(Menu)`: adds welcome message, special prompt without b/h hints
- Menu tree built declaratively (like PerCell 1's `MenuFactory`)

## Resolved Questions

1. **TUI vs CLI?** — Stay with Rich CLI. TUI frameworks add complexity without matching the sequential workflow model.
2. **80x24 constraint?** — No. Allow dynamic terminal sizing. Rich auto-detects width for tables.
3. **Arrow-key navigation?** — Not for now. Numbered input is universally understood by scientists. Could add `simple-term-menu` as optional dependency later if user feedback requests it.
4. **Where does experiment context go?** — Below the banner, above the menu title. Visible on every screen.

## Resolved Questions (continued)

5. **Plugin manager** — Show as a grayed-out/disabled item in the main menu so users know it's planned. Matches current PerCell 3 behavior.
6. **Help system** — Always available via `?` key at any prompt. Not a numbered menu item. Prompt hints show `?=help`.
7. **Query depth** — Data sub-menu has 4 items (Query experiment, Edit, Export, Back). Query experiment opens a third-tier menu with summary, channels, FOVs, conditions, bio-reps. This is the one place where three tiers makes sense because it's a read-only inspection tool.

## Final Menu Tree

```
MAIN MENU:
  1. Setup       - Create and select experiments
  2. Import      - Import LIF, TIFF, or CZI images
  3. Segment     - Single-cell segmentation with Cellpose
  4. Analyze     - Measure, threshold, and analyze cells
  5. View        - View images and masks in napari
  6. Data        - Query, edit, and export experiment data
  7. Workflows   - Run automated analysis pipelines
  8. Plugins     - Extend functionality with plugins (coming soon)
  9. Exit

SETUP MENU:
  1. Create experiment     - Create a new .percell experiment
  2. Select experiment     - Open an existing experiment
  3. Back to Main Menu

IMPORT MENU:
  1. Import images         - Load LIF, TIFF, or CZI files
  2. Back to Main Menu

SEGMENT MENU:
  1. Segment cells         - Run Cellpose segmentation
  2. Back to Main Menu

ANALYZE MENU:
  1. Measure channels      - Measure fluorescence intensities per cell
  2. Apply threshold       - Otsu thresholding and particle detection
  3. Back to Main Menu

VIEW MENU:
  1. View in napari        - Open images and masks in napari viewer
  2. Back to Main Menu

DATA MENU:
  1. Query experiment      - Inspect experiment data
  2. Edit experiment       - Rename conditions, FOVs, channels, bio-reps
  3. Export to CSV          - Export measurements and particle data
  4. Back to Main Menu

  QUERY MENU (under Data > Query):
    1. Experiment summary    - Per-FOV overview of cells and measurements
    2. Channels              - List channels in the experiment
    3. FOVs                  - List fields of view
    4. Conditions            - List experimental conditions
    5. Biological replicates - List biological replicates
    6. Back to Data Menu

WORKFLOWS MENU:
  1. Run workflow           - Run automated analysis pipelines
  2. Back to Main Menu
```
