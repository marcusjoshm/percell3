---
status: pending
priority: p3
issue_id: "031"
tags:
  - code-review
  - io
  - documentation
dependencies: []
---

# Document source_files as Transient (Not Serialized)

## Problem Statement

`ImportPlan.source_files` is not included in YAML serialization, which is intentional (file lists are ephemeral), but this behavior is not documented. A user or developer might expect round-trip fidelity and be surprised when the field is lost.

## Findings

- **Agent**: kieran-python-reviewer (HIGH severity)
- **Location**: `src/percell3/io/models.py:112`, `src/percell3/io/serialization.py`

## Proposed Solutions

Add a docstring note to `source_files` field and optionally a test documenting the intended behavior.
- Effort: Trivial

## Work Log

### 2026-02-14 — Identified during code review
