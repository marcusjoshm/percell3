---
status: pending
priority: p1
issue_id: 164
tags: [code-review, correctness, image-calculator]
dependencies: []
---

# channel_b falsy check uses truthiness instead of identity

## Problem Statement

In `image_calculator.py:125`, the check for whether `channel_b` was provided uses `if not channel_b:` which treats an empty string `""` the same as `None`. The correct semantic check is `if channel_b is None:`.

While channel names are unlikely to be empty strings in practice, this is a correctness bug that violates Python best practices for optional parameter checking.

## Findings

- **Source**: kieran-python-reviewer (Finding #3)
- **Location**: `src/percell3/plugins/builtin/image_calculator.py:125`
- **Current code**: `if not channel_b:`
- **Should be**: `if channel_b is None:`

## Proposed Solutions

### Option A: Fix the identity check (Recommended)

Change `if not channel_b:` to `if channel_b is None:`.

- **Pros**: One-line fix, semantically correct
- **Cons**: None
- **Effort**: Small
- **Risk**: None

## Acceptance Criteria

- [ ] `channel_b` check uses `is None` instead of falsy check
- [ ] Tests still pass

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-03 | Created from code review | Use identity checks for optional params |
