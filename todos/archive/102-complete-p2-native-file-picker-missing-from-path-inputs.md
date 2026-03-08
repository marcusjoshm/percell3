---
status: complete
priority: p2
issue_id: "102"
tags: [code-review, cli, ux, file-picker]
dependencies: []
---

# Native file picker not offered for all path inputs

## Problem Statement

The native OS file picker (tkinter `filedialog`) is only available in the import source flow (`_prompt_source_path()` at menu.py:1828). Other path input points — create experiment, select experiment, export CSV output path, Prism export output directory, particle workflow export directory — only accept typed paths with no option to browse using the native file manager.

Users expect to be able to use the native file picker anywhere a directory or file path is requested.

## Findings

- **Found by:** User testing
- **Location:** `src/percell3/cli/menu.py`
- **Affected prompts:**
  - `_create_experiment()` (line 622) — path for new experiment
  - `_select_experiment()` (line 602/606) — path to existing experiment
  - `_export_csv()` (line 2124) — output CSV path
  - `_export_prism()` (line 2249) — output directory path
  - `_particle_workflow()` (line 2381) — output directory for Prism export
- **Working example:** `_prompt_source_path()` (line 1828) shows the pattern — offers [1] Type path, [2] Browse for folder, [3] Browse for files

## Proposed Solutions

### Solution A: Extract reusable `_prompt_path()` helper (Recommended)
- Create a `_prompt_path(prompt, mode="dir"|"file"|"save")` helper that offers type/browse options
- Replace all inline `menu_prompt("Path ...")` calls with this helper
- Reuse the tkinter pattern from `_prompt_source_path()`
- **Effort:** Small | **Risk:** Low

### Solution B: Add browse option case-by-case
- Add the browse option inline to each path prompt
- More duplication but less refactoring
- **Effort:** Small | **Risk:** Low

## Acceptance Criteria

- [ ] Create experiment offers native folder picker
- [ ] Select experiment offers native folder picker
- [ ] Export CSV offers native file save dialog
- [ ] Prism export offers native folder picker
- [ ] Particle workflow export offers native folder picker
- [ ] Falls back gracefully when tkinter unavailable

## Work Log

- 2026-02-25: Identified during user interface testing
