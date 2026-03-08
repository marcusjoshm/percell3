---
status: complete
priority: p1
issue_id: "056"
tags: [code-review, napari-viewer, error-handling, data-loss]
dependencies: []
---

# Bare `except Exception` in Label Layer Loading — Silent Data Loss

## Problem Statement
In `src/percell3/segment/viewer/_viewer.py:197`, the `_load_label_layer()` function wraps the entire label-loading path in `except Exception` and silently falls back to an empty label layer. This means any real error (corrupted Zarr store, permission denied, out of memory, wrong dtype) is swallowed, and the user sees an empty canvas with no indication that their actual labels failed to load. This is a data-loss risk: the user edits an empty label layer thinking their data is fresh, closes napari, and the save-back pipeline overwrites real labels with zeros.

## Findings
- **File:** `src/percell3/segment/viewer/_viewer.py:197`
- Flagged by: kieran-python-reviewer (C1), security-sentinel (Finding 1), code-simplicity-reviewer
- The bare except catches everything from KeyError to MemoryError
- Combined with the dict-key bug (todo-057), label loading *always* fails and silently falls through to empty labels

## Proposed Solutions

### Option 1 (Recommended): Catch only expected exceptions, re-raise others
Catch `KeyError` or `FileNotFoundError` for the "no labels yet" case. Let everything else propagate. Show a warning to the user via `click.echo` or `warnings.warn`.

### Option 2: Log the exception and show user warning
Keep a broader catch but log the full traceback and show a visible warning in the napari viewer title or via a dialog.

## Acceptance Criteria
- [ ] Only expected "no labels found" errors are caught
- [ ] Real exceptions propagate or are displayed with full context
- [ ] User is informed when label loading fails for unexpected reasons
- [ ] Tests verify that unexpected errors are not swallowed
