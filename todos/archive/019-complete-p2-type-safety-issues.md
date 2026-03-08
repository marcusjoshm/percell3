---
status: pending
priority: p2
issue_id: "019"
tags: [code-review, quality, cli, types]
dependencies: []
---
# Type Safety Issues Across CLI Module

## Problem Statement
Multiple type safety issues reduce static analysis effectiveness and violate project conventions (CLAUDE.md requires type hints on all public functions, dataclasses for value objects).

## Findings

### 1. Missing type imports in import_cmd.py
- `import_cmd.py:122`: `_show_preview(scan_result: "ScanResult")` — `ScanResult` never imported
- `import_cmd.py:62`: `_run_import(store: "ExperimentStore")` — `ExperimentStore` never imported
- Works at runtime due to `from __future__ import annotations` but static type checkers report errors

### 2. error_handler strips type information
- `utils.py:36`: `error_handler(func: Callable[..., Any]) -> Callable[..., Any]` erases all parameter/return types
- Should use `ParamSpec` + `TypeVar` for proper typed decorator pattern

### 3. _PRESETS uses untyped dict values
- `workflow.py:18-27`: `_PRESETS` is `dict[str, dict[str, Any]]` — accessing `["factory"]` returns `Any`
- Should use a dataclass or TypedDict per CLAUDE.md conventions

### 4. MenuItem is raw tuple instead of dataclass
- `menu.py:15`: `MenuItem = tuple[str, str, Callable[...] | None, bool]`
- CLAUDE.md says "dataclasses for value objects, no NamedTuples"
- 4-element tuple with positional meaning is fragile

**Source:** kieran-python-reviewer CRITICAL-2/3, HIGH-6/7

## Proposed Solutions
### Option A: Fix all type issues (Recommended)
1. Add missing imports to import_cmd.py (TYPE_CHECKING guard)
2. Use ParamSpec/TypeVar for error_handler
3. Replace _PRESETS dict with PresetWorkflow dataclass
4. Replace MenuItem tuple alias with frozen dataclass

Pros: Full type checker compliance, better IDE support
Cons: Multiple small changes across files
Effort: Small-Medium

## Acceptance Criteria
- [ ] mypy/pyright reports no errors on CLI module files
- [ ] error_handler preserves wrapped function signatures
- [ ] _PRESETS uses typed container (dataclass or TypedDict)
- [ ] MenuItem is a frozen dataclass
- [ ] All existing tests pass

## Work Log
### 2026-02-13 - Code Review Discovery
Kieran-python-reviewer identified 4 type safety issues across 4 files.
