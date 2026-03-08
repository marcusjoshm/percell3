---
status: pending
priority: p2
issue_id: "145"
tags: [code-review, duplication, cli]
---

# FOV Selection Pattern Duplicated in menu.py

## Problem Statement
The pattern `filter to fovs_with_cells -> show_table -> auto-select-if-one -> select` is repeated across menu.py, creating maintenance risk and inconsistency. The decapping workflow and other additions have expanded the duplication since the original audit.

## Findings
- **File:** `src/percell3/cli/menu.py`
- **Verified:** 2026-03-08
- Found by: code-simplicity-reviewer

### "fovs_with_cells" filter + show_table + select pattern (6 instances):
  - Line 891 (measure menu)
  - Line 1043 (threshold menu, with extra filter for thresholds)
  - Line 2478 (particle analysis)
  - Line 2564 (grouping)
  - Line 2882 (export CSV)
  - Line 4619 (decapping workflow)

### Broader _select_fovs_from_table calls (14 total):
  - Also at lines 607, 716, 1171, 2244, 3992, 4149, 4209, 4274 (various menus using all_fovs or filtered lists)

### _show_fov_status_table calls (15 total, including definition at line 1800)

## Proposed Solutions
1. Extract `_select_fovs_with_cells(store)` helper for the 6-instance pattern (~50 LOC saved)
2. Extract `_prompt_optional_int(prompt, default, min_val)` helper (~50 LOC saved)
