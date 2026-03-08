---
status: pending
priority: p2
issue_id: "149"
tags: [code-review, performance, pandas]
---

# iterrows() in measurer.py Is 10-100x Slower Than itertuples()

## Problem Statement
`_measure_cells_on_channel` uses `cells_df.iterrows()` which converts each row to a Series with type inference. `itertuples()` is 10-100x faster.

## Findings
- **File:** `src/percell3/measure/measurer.py:258, 196`
- Found by: performance-oracle (OPT-4)

## Proposed Solutions
1. Replace `for _, cell in cells_df.iterrows()` with `for cell in cells_df.itertuples()`
