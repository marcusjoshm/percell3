---
status: pending
priority: p2
issue_id: "036"
tags: [code-review, segment, api-design]
dependencies: []
---

# SegmentationEngine.run() Does Not Expose All SegmentationParams Fields

## Problem Statement

`SegmentationEngine.run()` accepts `channel`, `model`, and `diameter`, but hardcodes defaults for `flow_threshold`, `cellprob_threshold`, `gpu`, `min_size`, `normalize`, and `channels_cellpose`. Users and agents cannot tune these through the high-level API without reimplementing the orchestration loop.

## Findings

- **File:** `src/percell3/segment/_engine.py:35-62`
- `run()` constructs `SegmentationParams` internally with only 3 of 9 fields exposed
- Common optimization workflow (adjusting `flow_threshold`, `cellprob_threshold`) requires dropping to low-level API

## Proposed Solutions

### Option 1 (Recommended): Accept optional `SegmentationParams`

```python
def run(self, store, channel="DAPI", model="cyto3", diameter=None,
        regions=None, condition=None, progress_callback=None,
        *, params: SegmentationParams | None = None) -> SegmentationResult:
```

When `params` is provided, it overrides `channel`/`model`/`diameter`. Backward-compatible.

### Option 2: Forward all keyword arguments

Expose all SegmentationParams fields as kwargs on `run()`.

## Acceptance Criteria

- [ ] All SegmentationParams fields accessible through `SegmentationEngine.run()`
- [ ] Backward-compatible with existing call sites
- [ ] Tests for custom params path

## Work Log

### 2026-02-16 — Code Review Discovery
Identified by agent-native-reviewer. Blocks agent-driven parameter optimization workflows.
