---
status: pending
priority: p3
issue_id: "023"
tags: [code-review, cli, agent-native]
dependencies: []
---
# Workflow List Needs --format Option for Machine-Readable Output

## Problem Statement
`percell3 workflow list` only outputs Rich-formatted tables. Unlike the query subcommands which support `--format json|csv|table`, workflow list has no machine-readable output option. Agents/scripts parsing this output must scrape ANSI-decorated markup.

## Findings
- `workflow.py:35-55`: workflow_list only renders Rich Table
- Query commands (`query.py`) support `--format` with json/csv/table options
- Inconsistency between command groups

**Source:** agent-native-reviewer CRITICAL-3

## Proposed Solutions
### Option A: Add --format option consistent with query commands
Add `--format` (`table|json|csv`) to `workflow list`, consistent with query subcommands.

Pros: Consistent API, scriptable
Effort: Small

## Acceptance Criteria
- [ ] `percell3 workflow list --format json` outputs valid JSON
- [ ] Default format remains table
- [ ] Consistent with query command --format behavior

## Work Log
### 2026-02-13 - Code Review Discovery
Agent-native-reviewer flagged missing machine-readable output for workflow list.
