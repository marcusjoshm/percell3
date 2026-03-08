---
status: pending
priority: p2
issue_id: 154
tags: [code-review, performance, io]
dependencies: []
---

# Peak Memory 2x Canvas — Stream Tiles into Canvas

## Problem Statement

The current tile stitching flow reads ALL tile images into a list (`tile_images`), then allocates a canvas and copies tiles into it. At peak, both the tile list and the canvas are alive in memory — approximately 2x the final canvas size. For a 10x10 grid of 2048x2048 uint16 images, this is ~1.6 GB peak. The 2 GB memory guard only checks canvas size, not total allocation.

Known pattern from `docs/solutions/logic-errors/io-module-p1-z-projection-and-input-validation-fixes.md` — streaming accumulation reduces peak memory by ~50%.

## Findings

- **Source**: performance-oracle, security-sentinel, learnings-researcher
- **Location**: `src/percell3/io/engine.py:266-293` (_read_and_stitch_tiles), `src/percell3/io/engine.py:414-467` (stitch_tiles)
- **Evidence**: `tile_images: list[np.ndarray]` holds all tiles, then `canvas = np.zeros(...)` allocated separately

## Proposed Solutions

### Option A: Stream tiles directly into pre-allocated canvas (Recommended)
- **Pros**: Halves peak memory, memory guard becomes accurate, fail-fast on dimension mismatch
- **Cons**: `stitch_tiles()` standalone function needs to be kept for tests
- **Effort**: Medium
- **Risk**: Low

Read first tile to get dimensions/dtype, allocate canvas, then read remaining tiles one-at-a-time directly into canvas positions.

### Option B: Keep current approach, fix memory guard to check tiles + canvas
- **Pros**: Simpler change
- **Cons**: Still 2x memory, just better guarded
- **Effort**: Small
- **Risk**: Low

## Technical Details

- **Affected files**: `src/percell3/io/engine.py`

## Acceptance Criteria

- [ ] Peak memory for tile stitching is ~1x canvas + 1 tile (not ~2x)
- [ ] Memory guard accounts for post-Z-transform dtype
- [ ] All existing stitch tests still pass

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-02 | Created from code review | Known pattern from docs/solutions |
