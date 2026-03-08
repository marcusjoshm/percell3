---
status: pending
priority: p3
issue_id: "022"
tags: [code-review, quality, cli]
dependencies: []
---
# Query Output Format Boilerplate (DRY Violation)

## Problem Statement
Every query subcommand (channels, regions, conditions) repeats the same `if fmt == "table" / elif fmt == "csv" / elif fmt == "json"` branching pattern (~90 lines total). The format dispatch should be extracted into a shared helper.

## Findings
- `query.py:36-64` (channels): table/csv/json branching
- `query.py:67-107` (regions): same branching repeated
- `query.py:110-135` (conditions): same branching repeated
- Each branch constructs Rich Table, or calls csv.writer, or json.dumps

**Source:** code-simplicity-reviewer #4

## Proposed Solutions
### Option A: Extract format dispatch helper
Create a `_output_results(rows, columns, fmt)` helper that handles table/csv/json rendering. Each subcommand calls it with data and column definitions.

Pros: DRY, easier to add new formats later
Effort: Small

## Acceptance Criteria
- [ ] Format dispatch logic exists in one place
- [ ] All three query subcommands use the shared helper
- [ ] All output formats produce identical results to current implementation
- [ ] All existing tests pass

## Work Log
### 2026-02-13 - Code Review Discovery
Code-simplicity-reviewer flagged repeated output format branching across query subcommands.
