---
status: pending
priority: p2
issue_id: "039"
tags: [code-review, core, performance]
dependencies: []
---

# Row-by-Row Cell Insertion Should Use `executemany()`

## Problem Statement

`queries.insert_cells()` executes individual INSERT statements per cell. For experiments with many regions and cells (100 regions x 2000 cells = 200K inserts), this becomes a significant bottleneck. Also, label data is cast to `int32` up to 3 times as it flows through the pipeline, creating unnecessary memory copies.

## Findings

- **File:** `src/percell3/core/queries.py:333-361` — row-by-row insertion
- **Triple astype:** cellpose_adapter.py:71, zarr_io.py:272, roi_import.py:63 all call `.astype(np.int32)`
- For 4096x4096 images, each copy is 64MB; triple-copy wastes 128MB

## Proposed Solutions

### Option 1 (Recommended): Use `executemany()` for bulk insert

```python
conn.executemany(sql, [(c.region_id, ...) for c in cells])
```

Expected 3-5x speedup for cell insertion.

### Option 2: Reduce astype copies

Check dtype before copying: `if data.dtype != np.int32: data = data.astype(np.int32)`

## Acceptance Criteria

- [ ] `insert_cells` uses `executemany()` or equivalent batch approach
- [ ] Label data is cast to int32 only when necessary (check before copy)
- [ ] Performance test shows improvement

## Work Log

### 2026-02-16 — Code Review Discovery
Identified by performance-oracle. Scaling concern for large experiments.
