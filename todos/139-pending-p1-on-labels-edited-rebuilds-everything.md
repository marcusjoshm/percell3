---
status: pending
priority: p1
issue_id: "139"
tags: [code-review, performance]
---

# on_labels_edited Rebuilds All Cells Instead of Delta

## Problem Statement
`auto_measure.on_labels_edited()` deletes ALL cells for a FOV and re-extracts from scratch, even when only a single cell boundary was adjusted. For a 200-cell FOV with 4 channels, this triggers deletion of ~4800 measurements and complete re-computation. In napari, this creates multi-second freezes after every brush stroke.

## Findings
- **File:** `src/percell3/measure/auto_measure.py:156-203`
- Found by: performance-oracle (CRITICAL-1)
- The function already receives `old_labels` and `new_labels` but ignores the delta

## Proposed Solutions
1. **Delta detection** — Compare `old_labels != new_labels`, find affected label IDs with `np.unique`, delete only affected cells, re-extract and re-measure only those cells. Reduces O(N*C*M) to O(delta*C*M).

## Acceptance Criteria
- [ ] Editing 1 cell in a 200-cell FOV only re-measures that cell
- [ ] `np.array_equal` short-circuit for no-change edits
- [ ] All existing auto_measure tests pass
