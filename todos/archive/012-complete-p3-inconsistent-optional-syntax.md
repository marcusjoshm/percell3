---
status: pending
priority: p3
issue_id: "012"
tags: [code-review, quality]
dependencies: []
---
# Inconsistent Optional[X] vs X | None

## Problem Statement
The codebase mixes `Optional[X]` (from typing) and `X | None` syntax for optional type annotations. The project targets Python 3.10+ and most files already have `from __future__ import annotations`.

## Findings
- `exceptions.py` uses `str | None` (modern syntax)
- All other files use `Optional[str]` from typing
- Project targets Python 3.10+, where `X | None` is natively supported
- Most files already import `from __future__ import annotations`
- `Optional` imports from `typing` are unnecessary when using `X | None`

## Proposed Solutions
### Option 1
Replace all `Optional[X]` usages with `X | None` across the codebase. Remove `from typing import Optional` imports where they become unused.

## Acceptance Criteria
- [ ] No remaining uses of `Optional[X]` in `src/percell3/core/`
- [ ] All files use `X | None` syntax consistently
- [ ] Unused `Optional` imports removed
- [ ] All existing tests still pass

## Work Log
### 2026-02-12 - Code Review Discovery
