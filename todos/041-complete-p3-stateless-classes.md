---
status: pending
priority: p3
issue_id: "041"
tags: [code-review, segment, simplification]
dependencies: []
---

# `LabelProcessor` and `RoiImporter` Are Stateless Classes — Could Be Functions

## Problem Statement

Both `LabelProcessor` and `RoiImporter` have no `__init__` parameters, no instance state, and are instantiated then immediately called. They are functions wrapped in unnecessary classes.

## Findings

- `LabelProcessor`: no `__init__`, one method (`extract_cells`), instantiated 3 times across 2 files
- `RoiImporter`: no `__init__`, two methods, instantiated then called in every usage

## Proposed Solutions

Convert to module-level functions. `extract_cells(...)` and `import_labels(...)` / `import_cellpose_seg(...)`.

Note: `CellposeAdapter` correctly uses state (model cache) and should remain a class.

## Acceptance Criteria

- [ ] `LabelProcessor` -> `extract_cells()` function
- [ ] `RoiImporter` -> module-level functions
- [ ] All callers updated
- [ ] Tests updated

## Work Log

### 2026-02-16 — Code Review Discovery
Identified by code-simplicity-reviewer. Reduces cognitive load.
