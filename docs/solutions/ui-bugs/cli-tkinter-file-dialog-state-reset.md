---
title: "tkinter File Dialog Breaks on Second Use"
problem_type: ui-bugs
component: cli/menu
symptoms:
  - "Second tkinter file dialog opens with limited features/broken UI"
  - "File browser window is unresponsive or visually degraded on subsequent calls"
root_cause: "Multiple tk.Tk() instances corrupt tkinter event loop state"
resolution_type: bugfix
severity: medium
tags: [tkinter, cli, file-dialog]
date_solved: "2026-02-25"
---

# tkinter File Dialog Breaks on Second Use

## Problem Statement

The `_prompt_path()` function in the CLI menu provides a native file browser
via tkinter. The first use works correctly, but the second use opens a degraded
dialog with limited features, making it impossible to select a directory.

## Root Cause

Each call to `_prompt_path()` created a new `tk.Tk()` root window and destroyed
it after the dialog closed. In tkinter, creating multiple `Tk()` instances in
the same process corrupts the event loop state -- the internal widget registry
and event loop cannot be fully reset by `root.destroy()`.

```python
# BAD: creates and destroys a new root each time
root = tk.Tk()
root.withdraw()
result = filedialog.askdirectory(title=title)
root.destroy()  # does not fully clean up Tk state
```

## Solution

Cache a single hidden root window on the function object and reuse it across
all invocations. Never destroy the root between uses.

```python
# GOOD: reuse a single persistent root
if not hasattr(_prompt_path, "_tk_root") or not _prompt_path._tk_root.winfo_exists():
    _prompt_path._tk_root = tk.Tk()
    _prompt_path._tk_root.withdraw()
root = _prompt_path._tk_root
root.lift()
root.focus_force()
result = filedialog.askdirectory(title=title, parent=root)
```

Key details:
- `winfo_exists()` guards against the root being closed unexpectedly
- `root.lift()` and `root.focus_force()` ensure the dialog appears in front
- `parent=root` binds the dialog to the persistent root window
- Never call `root.destroy()` between dialog calls

## Prevention

- **Never create multiple `tk.Tk()` instances** in the same process. Use a
  singleton pattern (module-level or function-attribute) for the root window.
- **Test sequential dialog calls** -- opening a dialog twice in the same
  session should produce identical behavior both times.
- **Always pass `parent=root`** to filedialog functions to avoid orphaned
  dialog windows on some platforms.

## Affected Files

- `src/percell3/cli/menu.py` (`_prompt_path()`)

## Related

- [docs/brainstorms/2026-02-13-cli-interactive-menu-brainstorm.md](../../brainstorms/2026-02-13-cli-interactive-menu-brainstorm.md) -- CLI menu design
