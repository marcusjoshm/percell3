---
status: pending
priority: p2
issue_id: "146"
tags: [code-review, architecture]
---

# Direct _conn.execute Bypasses queries.py Layer

## Problem Statement
`ExperimentStore` has 12+ instances of `self._conn.execute(...)` for impact previews, reverse lookups, and fov_config cleanup, bypassing the `queries.py` module. This violates the architecture principle "All SQL goes through queries.py."

## Findings
- **File:** `src/percell3/core/experiment_store.py` — lines 828-849, 952-974, 647-651, 994-1004
- Found by: kieran-python-reviewer (H3)

## Proposed Solutions
1. Extract to `queries.py` as `select_segmentation_impact()`, `select_threshold_impact()`, etc.
