---
status: pending
priority: p2
issue_id: 167
tags: [code-review, performance, image-calculator]
dependencies: []
---

# Image Calculator unnecessary memory allocation and I/O

## Problem Statement

The Image Calculator has two performance issues that compound at scale: (1) `_apply_op` unconditionally allocates float64 copies even for bitwise operations that only need int64, and (2) unchanged channels are read into numpy and rewritten to the derived FOV instead of being copied at the zarr level.

## Findings

### 1. Float64 allocation for bitwise ops (performance-oracle CRITICAL-1)
- **Location**: `src/percell3/plugins/builtin/image_calculator_core.py:28-68`
- `_apply_op` always creates float64 copies at the top, even when only int64 is needed for bitwise ops.
- At 4096x4096: wastes ~256 MB per bitwise operation.

### 2. Unchanged channels read/written back (performance-oracle CRITICAL-2)
- **Location**: `src/percell3/plugins/builtin/image_calculator.py:179-190`
- For N channels, (N-1) or (N-2) channels are read, decompressed, allocated, compressed, and written with no modification.
- At 5 channels x 4096x4096: ~320 MB of unnecessary I/O.

### 3. In-place numpy operations not used (performance-oracle CRITICAL-1)
- Arithmetic ops like add/subtract could use `out=` parameter to reuse the float64 buffer.

## Proposed Solutions

### Option A: Restructure _apply_op + use out= (Recommended)

Move bitwise ops to early return before float64 allocation. Use `np.add(af, bf, out=af)` for arithmetic ops.

- **Pros**: Significant memory reduction, no API change
- **Cons**: Slightly more complex control flow
- **Effort**: Small
- **Risk**: Low (tests validate correctness)

### Option B: Add store.copy_image_channel for unchanged channels

Add a zarr-level copy method to ExperimentStore that avoids decompression/recompression.

- **Pros**: Eliminates dominant I/O cost
- **Cons**: Requires ExperimentStore API change
- **Effort**: Medium
- **Risk**: Low

## Acceptance Criteria

- [ ] Bitwise ops don't allocate float64 arrays
- [ ] Arithmetic ops reuse buffers where possible
- [ ] All 47 tests still pass

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-03 | Created from code review | Separate bitwise/arithmetic paths early |
