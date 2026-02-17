---
status: complete
priority: p3
issue_id: "066"
tags: [code-review, yagni, code-simplicity]
dependencies: []
---

# `_NAME_TO_COLORMAP` Over-populated with Speculative Entries (YAGNI)

## Problem Statement
`_NAME_TO_COLORMAP` in `_viewer.py` contains mappings for channel names that aren't used anywhere in the codebase (e.g., "Cy3", "Cy5", "mCherry", "tdTomato", etc.). These are speculative entries that may never be needed. The dict could be trimmed to only the channels actually used in tests and documentation.

## Findings
- **File:** `src/percell3/segment/viewer/_viewer.py` — `_NAME_TO_COLORMAP` dict
- Flagged by: code-simplicity-reviewer
- Only DAPI, GFP, RFP, and BF appear in tests/docs
- Extra entries add visual noise without providing value

## Proposed Solutions
### Option 1 (Recommended): Trim to used channels + add fallback
Keep DAPI, GFP, RFP, BF. Others get a sensible default colormap (e.g., "gray"). Add a comment explaining how to add new mappings.

### Option 2: Keep all entries
They're harmless and might be useful. Low priority.

## Acceptance Criteria
- [ ] Only actively-used channel mappings retained
- [ ] Fallback colormap for unknown channels documented
