---
status: pending
priority: p3
issue_id: "150"
tags: [code-review, simplification]
---

# Exception Hierarchy Over-Engineered (6 Identical Classes)

## Problem Statement
`exceptions.py` has 10 exception classes. 6 of them (`ChannelNotFoundError`, `ConditionNotFoundError`, etc.) are structurally identical — each stores a name/ID and formats a message. `RunNameError` is unreachable (queries.py raises `DuplicateError` first).

## Findings
- **File:** `src/percell3/core/exceptions.py` (108 lines)
- Found by: code-simplicity-reviewer (~60 LOC removable)

## Proposed Solutions
1. Collapse 6 classes into `EntityNotFoundError(entity_type, name)`. Remove `RunNameError`.
