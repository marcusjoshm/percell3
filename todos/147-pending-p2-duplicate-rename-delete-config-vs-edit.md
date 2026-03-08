---
status: pending
priority: p2
issue_id: "147"
tags: [code-review, duplication, cli]
---

# Duplicate Rename/Delete in Config Management vs Edit Menus

## Problem Statement
Config Management menu (lines 1252-1523) and Edit menu (lines 2667-2874) both offer rename and delete for segmentations and thresholds — two separate UI paths with slightly different implementations for the same operations.

## Findings
- **File:** `src/percell3/cli/menu.py`
- Found by: code-simplicity-reviewer (~90 LOC removable)

## Proposed Solutions
1. Remove Config Management rename/delete items (4-7) and keep Edit menu versions
