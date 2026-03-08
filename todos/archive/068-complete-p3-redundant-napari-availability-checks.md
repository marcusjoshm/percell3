---
status: complete
priority: p3
issue_id: "068"
tags: [code-review, code-simplicity, napari, redundancy]
dependencies: []
---

# Redundant napari Availability Checks in 3 Locations

## Problem Statement
napari availability is checked in three places: `viewer/__init__.py` (module-level `NAPARI_AVAILABLE`), `_viewer.py:_launch()` (runtime check), and `cli/view.py` (before calling launch). This triple-checking is redundant — a single authoritative check at the entry point would suffice.

## Findings
- **Files:** `viewer/__init__.py`, `_viewer.py`, `cli/view.py`
- Flagged by: code-simplicity-reviewer, kieran-python-reviewer (M5)
- Each location has slightly different error messages
- The CLI check is the user-facing one; the others are internal guards

## Proposed Solutions
### Option 1 (Recommended): Single check at CLI entry point
Remove the check in `_launch()`. Keep `NAPARI_AVAILABLE` in `__init__.py` as the flag. CLI checks the flag and shows the install message. `_launch()` trusts that the caller verified availability.

### Option 2: Keep all checks as defense-in-depth
They're cheap and provide safety. Just unify error messages.

## Acceptance Criteria
- [ ] Consistent error messaging across check points
- [ ] No redundant checks that can never trigger
