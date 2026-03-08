---
status: pending
priority: p2
issue_id: 135
tags: [code-review, quality, plugins]
---

# SplitHaloCondensateAnalysisPlugin.run() is 200+ lines

## Problem Statement
The `run()` method in `split_halo_condensate_analysis.py` handles parameter parsing, FOV iteration, per-cell granule measurement, per-cell dilute phase measurement, derived FOV creation, CSV export, and progress callbacks all in one method.

## Proposed Solutions

### A: Extract `_process_cell()` method
- Returns structured results (granule rows + dilute row + mask fragments)
- Makes per-cell logic independently testable
- **Effort:** Medium | **Risk:** Low

## Acceptance Criteria
- [ ] `run()` is under 100 lines
- [ ] Per-cell logic is in its own method
- [ ] All existing tests pass
