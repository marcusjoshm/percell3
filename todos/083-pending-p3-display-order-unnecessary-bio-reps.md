---
status: pending
priority: p3
issue_id: "083"
tags: [plan-review, yagni, schema]
dependencies: []
---

# Display Order Unnecessary on biological_replicates

## Problem Statement

The plan includes display_order on biological_replicates table. Bio reps are always N1, N2, N3... — alphabetical/natural sort is deterministic. Unlike channels where user controls ordering (DAPI first, then GFP), bio reps have no ambiguity.

## Findings

Simplicity reviewer: "Unnecessary. Natural sort order is deterministic. Remove it."

## Proposed Solutions

### A) Remove display_order from biological_replicates table

- **Effort:** Trivial
- **Risk:** None

Drop the display_order column from the biological_replicates CREATE TABLE statement. Bio reps are always sorted by their natural name ordering (N1, N2, N3...).

## Technical Details

The display_order column exists on the channels table where it serves a real purpose — users want DAPI listed before GFP regardless of insertion order. Bio reps have no such ambiguity; N1 < N2 < N3 is always the correct order.

## Acceptance Criteria

- [ ] biological_replicates schema has no display_order column

## Work Log

_No work performed yet._

## Resources

- Plan review: simplicity reviewer feedback
