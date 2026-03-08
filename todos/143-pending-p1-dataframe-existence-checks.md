---
status: pending
priority: p1
issue_id: "143"
tags: [code-review, performance]
---

# DataFrame-Based Existence Checks Should Use SQL LIMIT 1

## Problem Statement
`auto_measure._has_measurements()` and `_has_masked_measurements()` load entire DataFrames (all cells, all measurements) just to check if any measurements exist. For a 500-cell FOV with 3000 measurements, this constructs massive DataFrames to return a boolean.

## Findings
- **File:** `src/percell3/measure/auto_measure.py:312-356`
- Found by: performance-oracle (CRITICAL-4)
- Should use `SELECT 1 ... LIMIT 1` which returns in microseconds

## Proposed Solutions
1. **Add SQL existence queries** — Replace DataFrame construction with direct SQL: `SELECT 1 FROM measurements m JOIN cells c ON m.cell_id = c.id WHERE c.fov_id = ? AND c.segmentation_id = ? LIMIT 1`

## Acceptance Criteria
- [ ] Existence checks use SQL LIMIT 1, not DataFrame construction
- [ ] on_config_changed still correctly detects measurement gaps
