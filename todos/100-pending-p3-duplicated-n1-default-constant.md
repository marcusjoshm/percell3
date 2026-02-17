---
status: pending
priority: p3
issue_id: "100"
tags: [code-review, quality, core, io]
dependencies: []
---

# Duplicated `"N1"` Default Bio Rep Name

## Problem Statement

The default bio rep name `"N1"` appears as a string literal in both `schema.py:179` (schema creation) and `io/models.py:108` (`ImportPlan.bio_rep` default). If one changes, they could silently diverge.

## Findings

- **Found by:** kieran-python-reviewer
- **Evidence:** `schema.py:179`, `models.py:108`

## Proposed Solutions

### Solution A: Extract constant
- `DEFAULT_BIO_REP = "N1"` in a shared location, referenced by both files
- **Effort:** Small | **Risk:** Low

## Work Log

- 2026-02-17: Identified during code review
