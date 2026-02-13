---
status: pending
priority: p1
issue_id: "002"
tags: [code-review, quality]
dependencies: []
---
# Wrong Exception for Missing Condition

## Problem Statement

`queries.py:132` in `select_condition_id` raises `RegionNotFoundError` when a
condition is not found, despite an inline comment that reads
`"# condition not found"`. This produces misleading error messages that point
callers toward debugging region logic when the actual problem is a missing
condition.

## Findings

- `select_condition_id` at line 132 of `queries.py` raises `RegionNotFoundError`
  instead of a condition-specific error.
- The inline comment explicitly acknowledges the entity is a condition, but the
  wrong exception class is used -- likely a copy-paste error from a similar
  region-lookup function.
- Downstream callers that catch `RegionNotFoundError` will inadvertently swallow
  condition-not-found failures, and callers looking for a condition error will
  never see one.
- No `ConditionNotFoundError` currently exists in `exceptions.py`.

## Proposed Solutions

### Option 1 -- New `ConditionNotFoundError` (recommended)

1. Create `ConditionNotFoundError(PerCellError)` in `exceptions.py`, mirroring
   the pattern used for `RegionNotFoundError`.
2. Export it from `core/__init__.py`.
3. Replace the raise site in `select_condition_id` (queries.py:132).

### Option 2 -- Generic `EntityNotFoundError` with entity-type parameter

Define a single `EntityNotFoundError` that accepts an `entity_type` string
(e.g., `"condition"`, `"region"`). This reduces the number of exception
classes but makes except-clause filtering less precise.

## Technical Details

- **Files affected:** `queries.py:132`, `exceptions.py`, `core/__init__.py`
- **Risk:** Low. This is a straightforward exception-class swap. Callers that
  currently catch `RegionNotFoundError` to handle this case will need updating,
  but that existing behaviour is already incorrect.

## Acceptance Criteria

- [ ] `ConditionNotFoundError` defined in `exceptions.py` inheriting from the
      project base exception.
- [ ] `ConditionNotFoundError` exported from `core/__init__.py`.
- [ ] `select_condition_id` raises `ConditionNotFoundError` instead of
      `RegionNotFoundError`.
- [ ] Unit test asserts `ConditionNotFoundError` is raised for a non-existent
      condition name.
- [ ] Grep confirms no other call sites misuse `RegionNotFoundError` for
      condition lookups.

## Work Log

### 2026-02-12 - Code Review Discovery

Identified during manual review of `percell3.core`. The wrong exception class
is raised in `select_condition_id`, producing misleading error messages.
Classified as P1/quality because it masks real errors and complicates debugging.
