---
status: complete
priority: p1
issue_id: "043"
tags: [code-review, segment, data-integrity]
dependencies: []
---

# ROI Import Writes DB/Zarr Before Validating Region Exists — Orphaned Data

## Problem Statement

Both `import_labels()` and `import_cellpose_seg()` in `roi_import.py` create a segmentation run in the DB and write label data to Zarr **before** checking whether the target region exists. If the region is not found, a `ValueError` is raised at line 82/182, but by then orphaned records and Zarr data have already been persisted with no cleanup.

## Findings

- **`import_labels()`:** Creates run (line 65), writes labels (line 70), then validates region (line 74-79). If region missing -> ValueError at line 82, orphaned run + Zarr data.
- **`import_cellpose_seg()`:** Creates run (line 160), writes labels (line 171), then validates region (line 175-180). Same orphaned data problem.

## Proposed Solutions

### Option 1 (Recommended): Validate region existence first

Move the region lookup to the top of both methods, before any writes:

```python
def import_labels(self, labels, store, region, condition, ...):
    # Validate inputs first
    if not np.issubdtype(labels.dtype, np.integer): ...
    if labels.ndim != 2: ...

    # Validate region exists BEFORE writing anything
    region_info = store.get_regions(condition=condition)
    target_region = next((r for r in region_info if r.name == region), None)
    if target_region is None:
        raise ValueError(f"Region {region!r} not found in condition {condition!r}")

    # NOW create run and write labels
    run_id = store.add_segmentation_run(...)
    store.write_labels(...)
```

## Acceptance Criteria

- [ ] Region existence validated before any DB writes or Zarr writes
- [ ] Tests verify that failed import leaves no orphaned data
- [ ] Both `import_labels` and `import_cellpose_seg` fixed

## Work Log

### 2026-02-16 — Code Review Discovery
Identified by kieran-python-reviewer. Data integrity issue — orphaned records left on validation failure.
