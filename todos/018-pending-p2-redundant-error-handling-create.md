---
status: pending
priority: p2
issue_id: "018"
tags: [code-review, quality, cli]
dependencies: []
---
# Redundant Error Handling in create.py

## Problem Statement
`create.py` has both an `@error_handler` decorator AND an inner `try/except ExperimentError` that do the same thing. The decorator already catches `ExperimentError` and raises `SystemExit(1)`. The inner catch is redundant and confusing.

## Findings
- `create.py:17`: `@error_handler` decorator catches ExperimentError → prints error → SystemExit(1)
- `create.py:21-28`: Inner try/except also catches ExperimentError → prints error → SystemExit(1)
- The inner catch runs first, so the decorator's ExperimentError handler is dead code for this command
- The success message on line 30 is outside the try block but inside the decorator's scope

**Source:** kieran-python-reviewer CRITICAL-1, code-simplicity-reviewer #2

## Proposed Solutions
### Option A: Remove inner try/except, rely on @error_handler (Recommended)
Remove lines 21-28. Let @error_handler handle all exceptions uniformly across commands.

Pros: Consistent error handling, less code
Cons: None
Effort: Small

## Acceptance Criteria
- [ ] Only one error-handling mechanism per command (decorator OR inner catch)
- [ ] Error messages still display correctly for all failure modes
- [ ] All existing tests pass

## Work Log
### 2026-02-13 - Code Review Discovery
Two reviewers independently flagged the duplicate error handling pattern.
