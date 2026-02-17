---
status: pending
priority: p2
issue_id: "037"
tags: [code-review, segment, quality, duplication]
dependencies: []
---

# Duplicated Region-Lookup and Cell-Extraction Logic in roi_import.py

## Problem Statement

`import_labels()` and `import_cellpose_seg()` share ~25 lines of identical tail logic: region lookup, cell extraction, cell insertion, and cell count update. Also, the dtype branch in `import_cellpose_seg` (lines 161-164) has identical branches.

## Findings

1. **Lines 70-98 and 167-195** are nearly identical (write labels, lookup region, extract cells, insert, update count)
2. **Lines 161-164**: `if not integer: cast int32 else: cast int32` — both branches identical
3. Also found: redundant `import math` in `base_segmenter.py:5` and `import json` in `_engine.py:5`

## Proposed Solutions

### Option 1 (Recommended): Extract shared helper

```python
def _store_labels_and_cells(labels, store, region, condition, run_id):
    store.write_labels(region, condition, labels, run_id)
    # ... shared region lookup, cell extraction, insertion, count update
```

Also: fix redundant if/else to `masks = masks.astype(np.int32)`.
Remove unused imports.

## Acceptance Criteria

- [ ] Shared helper extracted, both methods use it
- [ ] Redundant if/else simplified
- [ ] Unused imports removed (`math` from base_segmenter.py, `json` from _engine.py)
- [ ] All tests pass

## Work Log

### 2026-02-16 — Code Review Discovery
Identified by code-simplicity-reviewer and kieran-python-reviewer. ~20 LOC of duplication.
