---
topic: Replace tkinter with Qt File Dialogs
date: 2026-02-27
status: deferred
---

# Replace tkinter with Qt File Dialogs

## What We're Building

Replace all tkinter file/folder dialog usage with Qt (`QFileDialog` via `qtpy`). This affects two functions in `menu.py`:
- `_prompt_path()` (7 call sites) — already has cached root workaround for tkinter bug
- `_prompt_source_path()` (1 call site) — still has the buggy create/destroy pattern

## Why This Change

tkinter file dialogs are buggy and unprofessional:
- Dialogs freeze/hang
- Dialogs appear behind other windows
- Crashes on macOS
- Multiple `Tk()` instances corrupt the event loop
- Existing workaround (cached root) is fragile

Qt is already a dependency via napari. `QFileDialog` is battle-tested, cross-platform, and provides native-looking dialogs on macOS, Windows, and Linux.

## Key Decisions

- **Library:** `qtpy` (already installed via napari dependency chain)
- **Fallback:** Keep existing typed-path input when Qt/display is unavailable (headless/SSH)
- **Scope:** Replace both `_prompt_path()` and `_prompt_source_path()` internals
- **No new dependencies:** qtpy is already in the dependency tree

## Scope

### In Scope
- [ ] Replace tkinter in `_prompt_path()` with `QFileDialog`
- [ ] Replace tkinter in `_prompt_source_path()` with `QFileDialog`
- [ ] Fix the still-buggy `_prompt_source_path()` pattern
- [ ] Maintain fallback to typed path when no display available
- [ ] Remove tkinter imports from menu.py
- [ ] Test on macOS (primary dev platform)

### Out of Scope
- Adding file dialogs to new places (separate todo #102)
- Qt-based message boxes or other widgets
- Removing tkinter from Python environment

## Technical Notes

- `QFileDialog.getOpenFileName()` — single file
- `QFileDialog.getOpenFileNames()` — multi-file (for TIFF import)
- `QFileDialog.getExistingDirectory()` — folder picker
- `QFileDialog.getSaveFileName()` — save dialog
- Need `QApplication.instance()` check — napari may or may not have started it
- If no `QApplication` exists, create a headless one or fall back to typed input

## Affected Files

- `src/percell3/cli/menu.py` — lines 182-244 (`_prompt_path`), lines 2130-2195 (`_prompt_source_path`)
- `docs/solutions/ui-bugs/cli-tkinter-file-dialog-state-reset.md` — can be archived after fix
- `todos/102-pending-p2-native-file-picker-missing-from-path-inputs.md` — related
