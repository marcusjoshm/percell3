---
title: "fix: CSV export crashes when given a directory path"
type: fix
date: 2026-02-20
---

# fix: CSV export crashes when given a directory path

## Problem

When the user enters a directory path (e.g. `/Users/leelab/Desktop`) instead of a file path for CSV export, the app crashes with:

```
Internal error: [Errno 21] Is a directory: '/Users/leelab/Desktop'
```

The measurement feature itself works fine (12005 measurements recorded). The bug is in the export path validation — both the interactive menu (`menu.py:1673`) and CLI command (`export.py:31`) pass directory paths straight to `pandas.to_csv()`, which raises `IsADirectoryError`.

A secondary issue: the overwrite check (`out_path.exists()`) fires for directories too, showing the misleading prompt "File exists. Overwrite?" before the crash.

## Files to modify

| File | Changes |
|------|---------|
| `src/percell3/cli/menu.py` | Fix `_export_csv()` — directory detection, auto-append filename, reorder checks |
| `src/percell3/cli/export.py` | Fix `export()` — directory detection, clear error message |
| `tests/test_cli/test_export.py` | Add tests for directory path, missing parent directory |

## Fix

### menu.py — `_export_csv()` (lines 1673-1710)

Restructure the path validation so the order is: **expand → directory check → overwrite check**.

After `out_path = Path(output_str).expanduser()`:

1. **Check `out_path.is_dir()`** — if true, auto-append `measurements.csv`, print info message: `"Path is a directory — exporting to {out_path}/measurements.csv"`
2. **Check `out_path.parent.exists()`** — if false, print error: `"Parent directory does not exist: {parent}"`, return
3. **Then** run the existing overwrite check on the final corrected path
4. **Wrap** `store.export_csv()` in `try/except OSError` to catch permission errors, disk full, etc. — display user-friendly message instead of crashing the menu session

### export.py — `export()` (lines 31-60)

After `out_path = Path(output).expanduser()`:

1. **Check `out_path.is_dir()`** — if true, print error: `"Error: Output path is a directory: {out_path}. Provide a file path, e.g. {out_path}/measurements.csv"`, exit 1
2. **Check `out_path.parent.exists()`** — if false, print error: `"Error: Parent directory does not exist: {parent}"`, exit 1
3. Both checks go **before** the existing overwrite check (directory check must precede `exists()` to avoid the misleading "file already exists" message)

### tests/test_export.py — new test cases

- `test_export_directory_path_rejected` — pass `tmp_path` (a directory) as output, assert exit code 1 and "directory" in output
- `test_export_directory_with_overwrite_still_rejected` — pass directory + `--overwrite`, still exit code 1
- `test_export_missing_parent_directory` — pass `tmp_path / "nonexistent" / "out.csv"`, assert exit code 1 and "does not exist" in output

## Design decisions

- **Interactive menu auto-corrects, CLI rejects.** The menu is conversational — auto-appending `measurements.csv` is helpful. The CLI is scriptable — silently changing the output path would be surprising. The CLI error message suggests the corrected path.
- **Don't auto-append `.csv` extension.** Users may intentionally want `.tsv` or other formats.
- **Don't auto-create parent directories.** A missing parent is likely a typo. Better to tell the user than silently `mkdir -p`.
- **Overwrite check must run on the final path.** After auto-appending `measurements.csv` to a directory, the overwrite check must fire on the new path, not the original directory.

## Verification

1. `pytest tests/test_cli/test_export.py -v`
2. `pytest tests/ -v` (no regressions)
