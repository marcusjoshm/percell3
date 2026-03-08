---
status: complete
priority: p2
issue_id: "026"
tags:
  - code-review
  - io
  - naming
  - maintainability
dependencies: []
---

# Scanner Variable Shadowing: `files` Parameter Clobbered

## Problem Statement

In `src/percell3/io/scanner.py`, the `scan()` method's `files` parameter (line 21) is shadowed by a local variable `files: list[DiscoveredFile]` on line 61. This works by accident because the parameter is only used before line 61, but is a maintenance trap — if anyone moves code or adds logic referencing the parameter after line 61, they get the wrong variable silently.

## Findings

- **Agent**: kieran-python-reviewer (CRITICAL severity in review)
- **Location**: `src/percell3/io/scanner.py:21,61`
- **Evidence**: Parameter `files: list[Path] | None = None` vs local `files: list[DiscoveredFile] = []`

## Proposed Solutions

### Option A: Rename local variable (Recommended)
Rename the local to `discovered_files`:
```python
discovered_files: list[DiscoveredFile] = []
```
Update all references within the method.
- Pros: Clear, no behavior change
- Cons: Touches many lines
- Effort: Small
- Risk: None

## Acceptance Criteria

- [ ] No variable shadowing in `FileScanner.scan()`
- [ ] All existing tests pass
- [ ] Linter/type checker clean

## Work Log

### 2026-02-14 — Identified during code review
- Found by kieran-python-reviewer agent
