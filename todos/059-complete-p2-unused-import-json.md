---
status: complete
priority: p2
issue_id: "059"
tags: [code-review, napari-viewer, dead-code]
dependencies: []
---

# Unused `import json` in Viewer Module

## Problem Statement
`src/percell3/segment/viewer/_viewer.py:5` has `import json` that is never used anywhere in the file. Dead import.

## Findings
- **File:** `src/percell3/segment/viewer/_viewer.py:5`
- Flagged by: kieran-python-reviewer (I1), code-simplicity-reviewer

## Proposed Solutions
### Option 1 (Recommended): Remove the import
Delete `import json` from line 5.

## Acceptance Criteria
- [ ] `import json` removed
- [ ] No references to `json` in the file
- [ ] ruff lint passes
