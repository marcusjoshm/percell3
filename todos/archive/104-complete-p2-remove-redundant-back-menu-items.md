---
status: complete
priority: p2
issue_id: "104"
tags: [code-review, cli, ux, menu]
dependencies: []
---

# Remove redundant "Back" menu items from sub-menus

## Problem Statement

Every sub-menu has a "Back" menu item as the last option (e.g., Setup has "3. Back", Import has "2. Back"). However, the `menu_prompt()` function already supports `b` (back) and `h` (home) navigation keys universally, and the prompt always shows "(h=home, b=back)". The "Back" menu item wastes screen space, adds visual clutter, and is redundant.

## Findings

- **Found by:** User testing
- **Location:** `src/percell3/cli/menu.py` — all sub-menu definitions
- **Affected menus:**
  - `_setup_menu()` line 230: `MenuItem("3", "Back", "", None)`
  - `_import_menu()` line 238: `MenuItem("2", "Back", "", None)`
  - `_segment_menu()` line 246: `MenuItem("2", "Back", "", None)`
  - `_analyze_menu()` line 255: `MenuItem("3", "Back", "", None)`
  - `_view_menu()` line 263: `MenuItem("2", "Back", "", None)`
  - `_data_menu()` line 274: `MenuItem("4", "Back", "", None)`
  - `_workflows_menu()` line 281: `MenuItem("2", "Back", "", None)`
  - `_query_menu()` line 1904: `MenuItem("6", "Back", "", None)`
  - `_edit_menu()` line 2043: `MenuItem("6", "Back", "", None)`
  - `_plugins_menu()` line 309: dynamically added Back item
- **Navigation already works:** `menu_prompt()` at line 65 handles `b` → `_MenuCancel()` and `h` → `_MenuHome()`
- **menu_system.py** line 85-87: `if item.handler is None: return` — "Back" items just exit the menu, same as pressing `b`

## Proposed Solutions

### Solution A: Remove all Back menu items (Recommended)
- Delete every `MenuItem(..., "Back", "", None)` from sub-menus
- The `b` key already does exactly the same thing
- **Effort:** Small | **Risk:** Low

## Acceptance Criteria

- [ ] No sub-menu shows a "Back" menu item
- [ ] `b` and `h` navigation still work in all sub-menus
- [ ] Plugins menu no longer adds a dynamic "Back" item

## Work Log

- 2026-02-25: Identified during user interface testing
