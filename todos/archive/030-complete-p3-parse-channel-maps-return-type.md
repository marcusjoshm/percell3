---
status: complete
priority: p3
issue_id: "030"
tags:
  - code-review
  - cli
  - type-safety
dependencies: []
---

# Bare `list` Return Type on _parse_channel_maps

## Problem Statement

`_parse_channel_maps()` in `import_cmd.py` has return type `-> list` instead of `-> list[ChannelMapping]`. This defeats type checking.

## Findings

- **Agent**: kieran-python-reviewer (HIGH severity)
- **Location**: `src/percell3/cli/import_cmd.py:192`
- **Evidence**: `def _parse_channel_maps(maps: tuple[str, ...]) -> list:`

## Proposed Solutions

Fix return type to `-> list[ChannelMapping]`.
- Effort: Trivial (1 line)

## Work Log

### 2026-02-14 — Identified during code review
