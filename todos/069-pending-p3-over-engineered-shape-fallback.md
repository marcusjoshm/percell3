---
status: pending
priority: p3
issue_id: "069"
tags: [code-review, code-simplicity, magic-number]
dependencies: []
---

# Over-engineered Shape Fallback Logic with Magic 512x512

## Problem Statement
In `_viewer.py`, when no channel images are found, a fallback shape of `(512, 512)` is used for the empty label layer. This magic number is arbitrary and the fallback logic adds complexity for an edge case that should arguably just error instead.

## Findings
- **File:** `src/percell3/segment/viewer/_viewer.py` — shape fallback logic
- Flagged by: code-simplicity-reviewer, kieran-python-reviewer (I5)
- 512x512 is an arbitrary default that doesn't match any real image size
- If no channels exist, showing a viewer with a random-size empty canvas is confusing

## Proposed Solutions
### Option 1 (Recommended): Error when no channel data exists
If `_load_channel_layers()` finds no channels, raise an error with a helpful message instead of showing an empty canvas.

### Option 2: Use first channel's shape as required
Require at least one channel to be present. Use its shape for the label layer.

## Acceptance Criteria
- [ ] No magic fallback dimensions
- [ ] Clear error when no image data available
- [ ] Shape derived from actual data
