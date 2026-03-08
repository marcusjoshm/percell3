---
status: resolved-by-refactor
priority: p2
issue_id: "148"
tags: [code-review, bug, cli]
---

# menu.py stat.get("run_id") References Wrong Key

> **Resolved by layer-based architecture redesign (2026-03-02).** The `segmentation_runs` table no longer exists. The engine now stores `segmentation_id` in fov_stats. Note: `menu.py` still references `stat.get("run_id")` at lines ~2319/2337 which will silently fail (returns `None`), but this is a residual cosmetic-only issue in post-segmentation display -- not the original architectural problem.

## Problem Statement
`_segment_cells` handler checks `stat.get("run_id")` but `SegmentationEngine.run()` stores `"segmentation_id"` in fov_stats. This silently prevents displaying per-FOV segmentation names after segmentation.

## Findings
- **File:** `src/percell3/cli/menu.py:1678-1697`
- Found by: kieran-python-reviewer (M7)

## Proposed Solutions
1. Change `stat.get("run_id")` to `stat.get("segmentation_id")`
