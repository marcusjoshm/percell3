---
status: complete
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

## Resolution

**Decision: No zero-padding. Use scanner-derived names or simple `FOV_1`, `FOV_2`, etc.**

- Scanner-derived FOV names are preserved verbatim during import (e.g., whatever the LIF/TIFF file provides).
- When auto-generating FOV names (e.g., single-FOV files), the convention is `FOV_1`, `FOV_2`, etc. — no zero-padding.
- SQL ordering uses the integer `fov_id` primary key, not the string name, so padding has no effect on sort order.
- The codebase already follows this convention — no zero-padded FOV names exist in the source.

## Work Log

- 2026-02-17: Identified during plan review
- 2026-02-18: Documented decision. Verified codebase uses no zero-padded FOV names. Marked complete.
