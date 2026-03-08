---
status: pending
priority: p3
issue_id: "015"
tags: [code-review, quality]
dependencies: []
---
# Dataclasses Should Be Frozen

## Problem Statement
All 4 model dataclasses are mutable but represent database records (value objects). Callers could mutate instances and mistakenly expect changes to persist back to the database.

## Findings
- Model dataclasses use `@dataclass` without `frozen=True`
- These classes represent immutable database records and should be treated as value objects
- Mutable instances create a risk of silent bugs where mutations are not persisted
- Frozen dataclasses also gain `__hash__` for free, enabling use in sets and as dict keys

## Proposed Solutions
### Option 1
Change all model dataclasses to use `@dataclass(frozen=True)`. Audit existing code for any in-place mutation of model instances and refactor to use `dataclasses.replace()` instead.

## Acceptance Criteria
- [ ] All model dataclasses use `@dataclass(frozen=True)`
- [ ] No existing code mutates model instances in-place
- [ ] Any necessary mutations use `dataclasses.replace()`
- [ ] All existing tests still pass

## Work Log
### 2026-02-12 - Code Review Discovery
