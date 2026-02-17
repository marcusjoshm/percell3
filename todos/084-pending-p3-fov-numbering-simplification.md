---
status: pending
priority: p3
issue_id: "084"
tags: [plan-review, yagni, ux]
dependencies: []
---

# FOV Numbering Simplification

## Problem Statement

The plan specifies FOV_001 (zero-padded). FOV_1 is simpler and sufficient. Zero-padding adds formatting complexity for no clear benefit.

## Findings

Simplicity reviewer: "Zero-padded FOV_001 is over-engineered. Use FOV_1 or preserve scanner-derived names."

## Proposed Solutions

### A) Use FOV_1, FOV_2 (no zero padding)

- **Effort:** Trivial
- **Risk:** None

Simple incrementing integers without zero-padding. Sorting in SQL uses the integer fov_id, not the string name, so padding is irrelevant for ordering.

### B) Use scanner-derived names; simple incrementing for auto-generated

- **Effort:** Trivial
- **Risk:** None

Preserve whatever name the scanner/file provides. When auto-generating (e.g., single-FOV files), use FOV_1, FOV_2, etc.

## Technical Details

Zero-padding requires deciding on a pad width (3? 4?) and adds f-string formatting logic. The actual FOV ordering in queries is determined by the integer primary key, not the display name. The only consumer of the padded name is human-readable output, where FOV_1 is perfectly clear.

## Acceptance Criteria

- [ ] Plan clarifies FOV naming convention (padded or not)

## Work Log

_No work performed yet._

## Resources

- Plan review: simplicity reviewer feedback
