---
status: complete
priority: p2
issue_id: "028"
tags:
  - code-review
  - cli
  - testing
dependencies: []
---

# Missing CLI Test for --auto-conditions Flag

## Problem Statement

The `--auto-conditions` flag was added to the `import` CLI command but has zero test coverage in the CLI test suite. The underlying `detect_conditions()` and `ImportEngine` with `condition_map` are tested, but the CLI glue that ties them together is not.

## Findings

- **Agent**: kieran-python-reviewer (MEDIUM severity)
- **Location**: `src/percell3/cli/import_cmd.py:39-41` (flag definition), `tests/test_cli/test_import.py` (no matching test)
- **Evidence**: `grep "auto.condition" tests/test_cli/test_import.py` returns no matches

## Proposed Solutions

### Option A: Add CliRunner tests (Recommended)
Add at least two tests:
- `test_import_with_auto_conditions` — files with multi-condition naming, verify conditions detected and used
- `test_import_auto_conditions_no_match` — files without matching pattern, verify fallback to single condition
- Pros: Direct test of the CLI flag
- Cons: None
- Effort: Small
- Risk: None

## Acceptance Criteria

- [ ] `--auto-conditions` flag tested with CliRunner
- [ ] Both detection and fallback paths covered
- [ ] All tests pass

## Work Log

### 2026-02-14 — Identified during code review
- Found by kieran-python-reviewer agent
