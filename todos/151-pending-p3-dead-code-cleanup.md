---
status: pending
priority: p3
issue_id: "151"
tags: [code-review, dead-code]
---

# Dead Code Cleanup

## Problem Statement
Several functions exist but are never called from production code.

## Findings
- `menu.py:3448-3450` — `_run_workflow` never referenced
- `menu.py:3453-3463` — `_show_help` never referenced
- `queries.py:231-235` — `select_bio_rep_id` never called
- `queries.py:43-45` — `get_experiment_description` never called
- `queries.py:1031-1057` — `update_fov_config_entry` only called from tests, not production. Also has sentinel value bug (Python C3) but moot if removed.
- Found by: code-simplicity-reviewer

## Proposed Solutions
1. Remove all dead functions. Remove the test that calls `update_fov_config_entry`.
