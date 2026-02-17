---
status: pending
priority: p3
issue_id: "032"
tags:
  - code-review
  - cli
  - agent-parity
dependencies: []
---

# Menu Export Silently Drops Channel/Metric Filters

## Problem Statement

The CLI `export` command supports `--channels` and `--metrics` filtering, but the interactive menu's `_export_csv()` handler calls `store.export_csv(out_path)` without any filtering options. Users in menu mode get all data with no way to filter.

## Findings

- **Agent**: agent-native-reviewer (WARNING parity gap)
- **Location**: `src/percell3/cli/menu.py:420` vs `src/percell3/cli/export.py:56`

## Proposed Solutions

Add channel/metric filter prompts to the menu export handler, or pass through to the shared export function.
- Effort: Small

## Work Log

### 2026-02-14 — Identified during code review
