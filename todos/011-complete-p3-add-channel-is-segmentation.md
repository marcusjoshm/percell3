---
status: pending
priority: p3
issue_id: "011"
tags: [code-review, quality]
dependencies: []
---
# add_channel Missing is_segmentation Parameter

## Problem Statement
ExperimentStore.add_channel does not expose the `is_segmentation` parameter, even though the underlying `queries.insert_channel` supports it and `ChannelConfig` has the field.

## Findings
- `ExperimentStore.add_channel` accepts channel name and wavelength but not `is_segmentation`
- `queries.insert_channel` already supports an `is_segmentation` column
- `ChannelConfig` dataclass includes the `is_segmentation` field
- Callers must work around this by manually updating the database after channel creation

## Proposed Solutions
### Option 1
Add `is_segmentation: bool = False` parameter to `ExperimentStore.add_channel` and forward it to `queries.insert_channel`.

## Acceptance Criteria
- [ ] `add_channel` accepts `is_segmentation: bool = False` parameter
- [ ] Value is forwarded to `queries.insert_channel`
- [ ] Existing callers are unaffected (default is False)
- [ ] Unit test covers adding a segmentation channel

## Work Log
### 2026-02-12 - Code Review Discovery
