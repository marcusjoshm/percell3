---
status: complete
priority: p2
issue_id: "027"
tags:
  - code-review
  - cli
  - performance
dependencies: []
---

# Double-Scan in Interactive Import Path

## Problem Statement

The interactive `_import_images()` handler in `menu.py` scans the TIFF directory once for preview (line 216), then `_run_import()` scans it again internally (line 111 of `import_cmd.py`). For large TIFF directories (hundreds of files), every file's metadata is read twice, doubling I/O time.

## Findings

- **Agent**: kieran-python-reviewer (HIGH severity)
- **Location**: `src/percell3/cli/menu.py:214-216` and `src/percell3/cli/import_cmd.py:111`
- **Evidence**: `scanner.scan(source)` called in menu.py, then `scanner.scan(Path(source))` again in `_run_import()`

## Proposed Solutions

### Option A: Pass scan_result into _run_import (Recommended)
Add optional `scan_result` parameter to `_run_import()`. When provided, skip the internal scan.
- Pros: Simple, backward compatible
- Cons: Makes `_run_import` signature slightly larger
- Effort: Small
- Risk: Low

### Option B: Extract scan to caller
Always scan in the caller and pass results through.
- Pros: Single responsibility
- Cons: Breaks current CLI command flow
- Effort: Medium
- Risk: Low

## Acceptance Criteria

- [ ] TIFF directory scanned only once in interactive import path
- [ ] CLI command path still works (single scan)
- [ ] All tests pass

## Work Log

### 2026-02-14 — Identified during code review
- Found by kieran-python-reviewer agent
