---
status: pending
priority: p3
issue_id: 136
tags: [code-review, architecture, viewer]
---

# Core copy functions live inside widget files

## Problem Statement
`copy_labels_to_fov()` and `copy_mask_to_fov()` are defined in their widget files. Tests import these functions, creating a transitive dependency on `qtpy`. Moving to a pure-Python module (e.g., `percell3/segment/copy_operations.py`) would cleanly separate domain logic from UI. This was done correctly for `bg_subtraction_core.py` but not for the copy operations.

## Acceptance Criteria
- [ ] Core functions in a non-Qt module
- [ ] Widget files import from the core module
- [ ] Tests don't need Qt installed
