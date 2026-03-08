---
status: pending
priority: p2
issue_id: "144"
tags: [code-review, performance]
---

# Redundant get_cells Queries in Auto-Measurement Chain

## Problem Statement
`on_segmentation_created()` calls `store.get_cells()`, then `measurer.measure_fov()` calls `store.get_cells()` again internally. For N FOVs with C channels, this creates 2N redundant database queries plus N*C `get_channel` queries.

## Findings
- **File:** `src/percell3/measure/auto_measure.py:57-85` and `src/percell3/measure/measurer.py:59`
- Found by: performance-oracle (CRITICAL-2)

## Proposed Solutions
1. Pass cells_df through to measurer to avoid re-querying
2. Cache label reads when same segmentation serves multiple FOVs (OPT-3)
