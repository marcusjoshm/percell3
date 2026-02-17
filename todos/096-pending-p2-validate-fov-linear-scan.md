---
status: pending
priority: p2
issue_id: "096"
tags: [code-review, performance, segment, roi-import]
dependencies: []
---

# `_validate_fov` in roi_import Does Linear Scan Instead of Direct Lookup

## Problem Statement

`_validate_fov()` in `roi_import.py` fetches ALL FOVs for a condition via `store.get_fovs()`, materializes them as dataclass instances, then does a Python for-loop to find the one matching the given name. A direct SQL lookup via `select_fov_by_name` already exists and would be O(1) via index.

## Findings

- **Found by:** performance-oracle
- **Evidence:** `roi_import.py:14-23` — fetches all FOVs, iterates in Python

## Proposed Solutions

### Solution A: Use store._resolve_fov or add a public lookup (Recommended)
- Replace the linear scan with `store._resolve_fov()` or a public `store.get_fov_by_name()` method
- **Effort:** Small | **Risk:** Low

## Acceptance Criteria

- [ ] `_validate_fov` uses indexed lookup instead of full scan
- [ ] Behavior unchanged: raises ValueError if FOV not found

## Work Log

- 2026-02-17: Identified during code review
