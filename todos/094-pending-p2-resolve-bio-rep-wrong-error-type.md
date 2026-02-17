---
status: pending
priority: p2
issue_id: "094"
tags: [code-review, architecture, core, exceptions]
dependencies: []
---

# `_resolve_bio_rep` Raises `BioRepNotFoundError` for Ambiguity Condition

## Problem Statement

When multiple bio reps exist and none is specified, `_resolve_bio_rep` raises `BioRepNotFoundError`. But the actual problem is ambiguity — multiple bio reps exist. "Not found" is semantically wrong. Callers who catch `BioRepNotFoundError` expecting "this bio rep doesn't exist" will also catch the ambiguity case.

## Findings

- **Found by:** kieran-python-reviewer
- **Evidence:** `experiment_store.py:179-181`

## Proposed Solutions

### Solution A: Use ValueError for ambiguity (Recommended)
- Raise `ValueError` when multiple bio reps exist and none specified
- Keep `BioRepNotFoundError` for actual "name doesn't exist" case
- **Effort:** Small | **Risk:** Low

### Solution B: Create AmbiguousBioRepError
- New exception subclass for the ambiguity case
- **Effort:** Small | **Risk:** Low — but may be over-engineering for 1 use site

## Acceptance Criteria

- [ ] Ambiguity raises a different exception than "not found"
- [ ] Error message includes available bio rep names

## Work Log

- 2026-02-17: Identified during code review
