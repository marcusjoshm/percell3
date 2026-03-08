---
status: complete
priority: p1
issue_id: "110"
tags: [code-review, segment, validation]
dependencies: []
---

# Missing edge_margin validation in SegmentationParams.__post_init__

## Problem Statement

Every numeric parameter on `SegmentationParams` is validated in `__post_init__` (min_size, flow_threshold, diameter, cellprob_threshold) except the new `edge_margin` field. A programmatic caller could pass `edge_margin=-5` and get silently wrong results.

## Findings

- **Found by:** kieran-python-reviewer, security-sentinel
- **Location:** `src/percell3/segment/base_segmenter.py:41-58`
- CLI validates `edge_margin >= 0` but the domain model does not self-protect

## Proposed Solutions

### Solution A: Add validation (one-liner)
Add to `__post_init__`:
```python
if self.edge_margin < 0:
    raise ValueError(f"edge_margin must be >= 0, got {self.edge_margin}")
```
- **Effort:** Small | **Risk:** Low

## Acceptance Criteria

- [ ] `SegmentationParams(edge_margin=-1)` raises ValueError
- [ ] Test added for negative edge_margin validation

## Work Log

- 2026-02-25: Identified during code review
