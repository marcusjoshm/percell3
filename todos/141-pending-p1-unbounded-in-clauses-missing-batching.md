---
status: pending
priority: p1
issue_id: "141"
tags: [code-review, sqlite, crash-risk]
---

# Unbounded IN Clauses Missing Batching (999 Parameter Limit)

## Problem Statement
Several query functions pass lists of arbitrary length into `IN (...)` clauses without batching. SQLite has a default limit of 999 bind parameters. With large experiments (1000+ cells), these functions will crash with `sqlite3.OperationalError: too many SQL variables`.

## Findings
- **Files:** `src/percell3/core/queries.py` — `select_measurements` (line 767), `select_cells` (line 681), `delete_cell_tags` (line 1304)
- **File:** `src/percell3/core/experiment_store.py:647-651` — `add_measurements` reverse lookup
- Found by: security-sentinel (F2), performance-oracle (OPT-1)
- `select_group_tags_for_cells` already correctly batches at 900 — same pattern should be applied everywhere

## Proposed Solutions
1. **Apply _BATCH_SIZE=900 pattern** — Add batching loop to all functions accepting unbounded lists. Use `constants.DEFAULT_BATCH_SIZE`.

## Acceptance Criteria
- [ ] All IN clause functions handle lists > 999 without crashing
- [ ] `DEFAULT_BATCH_SIZE` from constants.py used consistently (not local `_BATCH_SIZE`)
