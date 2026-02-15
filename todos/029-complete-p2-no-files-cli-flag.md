---
status: complete
priority: p2
issue_id: "029"
tags:
  - code-review
  - cli
  - agent-parity
dependencies: []
---

# No --files CLI Flag for File Picker Parity

## Problem Statement

The interactive menu's tkinter file picker allows selecting specific TIFF files (option 3 in `_prompt_source_path`), which passes `source_files` through to `_run_import()` and ultimately `ImportPlan.source_files`. However, the `import` CLI command has no `--files` option — it only accepts a single directory path. An agent or CI pipeline cannot selectively import a subset of files.

## Findings

- **Agent**: agent-native-reviewer (Critical parity gap)
- **Location**: `src/percell3/cli/import_cmd.py` (no `--files` option), `src/percell3/cli/menu.py:321-347` (file picker)
- **Evidence**: The plumbing exists in `_run_import()` via `source_files` parameter — it just needs a CLI flag

## Proposed Solutions

### Option A: Add --files Click option (Recommended)
```python
@click.option("--files", multiple=True, type=click.Path(exists=True),
              help="Specific TIFF files to import (instead of scanning directory).")
```
When provided, pass as `source_files` list to `_run_import()`.
- Pros: Full parity, plumbing already exists
- Cons: Slightly more complex import command
- Effort: Small
- Risk: Low

## Acceptance Criteria

- [ ] `percell3 import /dir -e exp --files img1.tif --files img2.tif` works
- [ ] Only specified files are imported (directory not scanned)
- [ ] All tests pass

## Work Log

### 2026-02-14 — Identified during code review
- Found by agent-native-reviewer agent
