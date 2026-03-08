---
status: pending
priority: p2
issue_id: "020"
tags: [code-review, quality, cli]
dependencies: []
---
# Dead and Unreachable Code in CLI Module

## Problem Statement
The CLI module contains dead imports and unreachable code that confuse readers and suggest incomplete refactoring.

## Findings

### 1. Unreachable code in workflow.py
- `workflow.py:100-114`: After `if name == "complete"` and `elif name == "measure_only"` branches both return early, the remaining code (building DAG, running engine, printing results) is unreachable
- Line 100 has `# pragma: no cover` acknowledging this
- This is speculative code for a future that doesn't exist yet

### 2. Dead imports in menu.py
- `menu.py:312`: `from percell3.cli.query import channels` — never used
- `menu.py:313`: `from click import Context` — never used
- Suggests an abandoned refactor to delegate to Click commands

**Source:** code-simplicity-reviewer #5, kieran-python-reviewer HIGH-5

## Proposed Solutions
### Option A: Remove dead code (Recommended)
Delete unreachable lines in workflow.py (100-114) and dead imports in menu.py (312-313).

Pros: Cleaner code, no confusion about intent
Cons: None
Effort: Small

## Acceptance Criteria
- [ ] No unreachable code in workflow.py
- [ ] No dead imports in menu.py
- [ ] All existing tests pass (including any that might reference these paths)

## Work Log
### 2026-02-13 - Code Review Discovery
Two reviewers flagged dead code patterns in workflow.py and menu.py.
