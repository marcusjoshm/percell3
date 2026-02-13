---
status: pending
priority: p2
issue_id: "006"
tags: [code-review, architecture]
dependencies: []
---

# Unused Run ID Parameters (YAGNI)

## Problem Statement

Several methods in `ExperimentStore` accept run ID parameters (`segmentation_run_id`, `threshold_run_id`) that are completely ignored in the implementation. These parameters create a false API contract: callers may pass different run IDs expecting to read or write distinct data, but the methods always operate on the same underlying zarr path regardless of the ID value. This violates the principle of least astonishment and sets a trap for future multi-run usage.

## Findings

- `read_labels` accepts `segmentation_run_id` but ignores it (`experiment_store.py:264-272`). All reads go to the same zarr group path.
- `read_mask` accepts `threshold_run_id` but ignores it (`experiment_store.py:398-407`). Same issue.
- `write_labels` accepts `segmentation_run_id` but does not incorporate it into the zarr path. Two writes with different run IDs silently overwrite each other.
- There is no infrastructure for multi-run storage (no run-indexed zarr groups, no run table in SQLite).
- Callers have no way to detect that the parameter is a no-op.

## Proposed Solutions

### Option 1

Remove the unused run ID parameters entirely until multi-run support is actually designed and implemented. This is the YAGNI-compliant approach. When multi-run support is needed, the parameters can be re-added alongside the storage infrastructure that makes them meaningful.

```python
# Before
def read_labels(self, region_id: int, segmentation_run_id: int | None = None) -> np.ndarray:

# After
def read_labels(self, region_id: int) -> np.ndarray:
```

### Option 2

If multi-run support is imminent, implement it properly now: add run-indexed zarr group paths (e.g., `labels/seg_run_{id}/`) and a `segmentation_runs` table in SQLite. However, this is significantly more work and should only be chosen if the feature is on the near-term roadmap.

## Technical Details

- Files affected: `src/percell3/core/experiment_store.py`, lines 264-272 (read_labels), 398-407 (read_mask), and the corresponding write_labels method.
- Removing the parameters is a breaking API change, but since they have no effect, any caller passing them is already buggy.
- A deprecation warning could be added as an intermediate step if callers exist in external code.

## Acceptance Criteria

- [ ] `read_labels`, `write_labels`, and `read_mask` no longer accept unused run ID parameters
- [ ] All call sites are updated (or confirmed to not pass these arguments)
- [ ] If multi-run is needed later, a design document is created before re-adding the parameters
- [ ] Tests pass without run ID arguments

## Work Log

### 2026-02-12 - Code Review Discovery

Identified during code review of `percell3.core`. The unused parameters violate YAGNI and create a misleading API surface. Callers cannot distinguish between "I'm using the default run" and "my run ID is being silently ignored."
