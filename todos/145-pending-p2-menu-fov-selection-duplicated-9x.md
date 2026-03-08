---
status: pending
priority: p2
issue_id: "145"
tags: [code-review, duplication, cli]
---

# FOV Selection Pattern Duplicated 9 Times in menu.py

## Problem Statement
The pattern `get_summary -> filter to fovs_with_cells -> show_table -> select` is repeated 9 times across menu.py. A 6-8 line block duplicated 9 times creates maintenance risk and inconsistency.

## Findings
- **File:** `src/percell3/cli/menu.py` — lines 485-496, 636-655, 1596-1603, 1836-1847, 1922-1933, 2260-2272, 3153-3160, and twice more in plugin handlers
- Found by: code-simplicity-reviewer
- Also 8+ duplicated numeric prompt patterns

## Proposed Solutions
1. Extract `_select_fovs_with_cells(store)` helper (~50 LOC saved)
2. Extract `_prompt_optional_int(prompt, default, min_val)` helper (~50 LOC saved)
