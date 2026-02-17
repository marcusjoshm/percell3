---
status: complete
priority: p1
issue_id: "057"
tags: [code-review, napari-viewer, bug, functional-correctness]
dependencies: []
---

# Dict Key Mismatch `channel_name` vs `channel` — Label Layer Always Empty

## Problem Statement
In `src/percell3/segment/viewer/_viewer.py:193`, the code uses `latest.get("channel_name")` to extract the segmentation channel from the most recent run. However, `ExperimentStore.select_segmentation_runs()` (in `src/percell3/core/queries.py:298-312`) returns dicts with key `"channel"` (aliased from SQL). This means `latest.get("channel_name")` always returns `None`, so `seg_channel` is always `None`, and `read_labels()` is called with `channel=None` — which likely fails or returns no data. Combined with the bare except (todo-056), this failure is silently swallowed, resulting in an always-empty label layer.

## Findings
- **File:** `src/percell3/segment/viewer/_viewer.py:193`
- **Root cause:** `select_segmentation_runs()` in `queries.py:298` aliases `seg_channel AS channel`, not `channel_name`
- Flagged by: kieran-python-reviewer (C2), security-sentinel (Finding 2)
- This is a functional correctness bug — labels NEVER load in the viewer

## Proposed Solutions

### Option 1 (Recommended): Fix the dict key
Change `latest.get("channel_name")` to `latest.get("channel")`.

### Option 2: Update the SQL query alias
Change the SQL alias in `select_segmentation_runs()` from `seg_channel AS channel` to `seg_channel AS channel_name` — but this would break all other consumers of that function.

## Acceptance Criteria
- [ ] `latest.get("channel")` used instead of `latest.get("channel_name")`
- [ ] Labels load correctly when a segmentation run exists
- [ ] Test added that verifies label loading with an actual segmentation run
