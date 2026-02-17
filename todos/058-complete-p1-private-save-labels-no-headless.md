---
status: complete
priority: p1
issue_id: "058"
tags: [code-review, napari-viewer, api-design, agent-parity]
dependencies: []
---

# `_save_edited_labels()` is Private — No Headless/Agent Access

## Problem Statement
The `_save_edited_labels()` function in `_viewer.py` is the only code path for saving edited labels back to the experiment store. It is a private function (prefixed with `_`) accessible only from within `_launch()` after napari closes. There is no public API or CLI command that allows saving labels headlessly. This means:
1. Agents cannot programmatically save labels
2. Automated workflows cannot use the save-back pipeline
3. Tests cannot exercise the save logic independently
4. The logic is duplicated with `RoiImporter` (which also saves labels)

## Findings
- **File:** `src/percell3/segment/viewer/_viewer.py` — `_save_edited_labels()` function
- Flagged by: agent-native-reviewer (Critical)
- `RoiImporter` has similar label-save logic (creates segmentation run, writes labels, extracts cells)
- No `percell3 save-labels` CLI command exists
- Agent parity violation: any action a user can take, an agent should also be able to take

## Proposed Solutions

### Option 1 (Recommended): Extract public `save_labels()` function
Create a public `save_labels(store, region, condition, labels, model_name="manual_edit")` function in the viewer module (or in the segment engine). Wire both `_launch()` and `RoiImporter` to use it. Add a `percell3 save-labels` CLI command.

### Option 2: Add CLI command that calls private function
Add `percell3 save-labels` that imports and calls `_save_edited_labels()`. Quick but doesn't fix the duplication.

### Option 3: Defer — document as known limitation
Document that headless label save is not yet supported. Add to backlog.

## Acceptance Criteria
- [ ] Public function available for saving labels headlessly
- [ ] CLI command exists for saving labels from command line
- [ ] Duplicate logic between viewer and RoiImporter is consolidated
- [ ] Tests exercise the save logic independently
