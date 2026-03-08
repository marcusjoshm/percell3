---
status: pending
priority: p2
issue_id: 134
tags: [code-review, architecture, viewer]
---

# Copy Labels/Mask widget duplication (~90% identical code)

## Problem Statement
`CopyLabelsWidget` and `CopyMaskWidget` are ~90% identical in their `__init__` methods (FOV combos, channel combo, apply button, status label). Only the apply logic differs. ~120 lines of pure duplication.

## Proposed Solutions

### A: Extract shared `BaseCopyWidget`
- Shared base provides FOV/channel UI, error display helper
- Subclasses override `_on_apply()`
- **Effort:** Small | **Risk:** Low

### B: Factory function for shared layout
- Function returns combo box references without inheritance
- **Effort:** Small | **Risk:** Low

## Acceptance Criteria
- [ ] No duplicated FOV/channel combo construction
- [ ] Both widgets retain identical UX
- [ ] Tests still pass
