---
status: pending
priority: p3
issue_id: "025"
tags: [code-review, security, cli]
dependencies: []
---
# Information Disclosure via Unfiltered Exception Messages

## Problem Statement
The generic error handler and menu handlers print full exception messages from unexpected exceptions directly to the terminal. This can disclose internal details (file paths, SQLite schema, library versions).

## Findings
- `utils.py:52`: `console.print(f"[red]Internal error:[/red] {e}")` — bare Exception catch
- `menu.py:112`: Same pattern for menu error handling
- `menu.py:154`: Same pattern for experiment opening errors
- Also: `error_handler` catches bare `Exception` broadly, converting all errors to SystemExit(2) which loses tracebacks during development

**Source:** security-sentinel MEDIUM-1, code-simplicity-reviewer #6

## Proposed Solutions
### Option A: Log full tracebacks to file, show sanitized messages to user
Log `traceback.format_exc()` to a debug log file. Show user-friendly message like "An internal error occurred. Run with --verbose for details."

Pros: Better security posture, debug info still available
Cons: Adds logging dependency
Effort: Small-Medium

### Option B: Remove broad Exception catch during development
Remove the bare Exception catch from error_handler. Let unexpected errors show Click's default traceback. Re-add sanitized error handling before release.

Pros: Better DX during development, stack traces visible
Cons: Raw tracebacks in production
Effort: Small

## Acceptance Criteria
- [ ] Internal error messages don't expose filesystem paths or library details
- [ ] Debug information still available via --verbose or log file
- [ ] All existing tests pass

## Work Log
### 2026-02-13 - Code Review Discovery
Security-sentinel flagged unfiltered exception messages as medium-severity information disclosure.
