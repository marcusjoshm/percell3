---
status: pending
priority: p2
issue_id: 168
tags: [code-review, quality, image-calculator, tests]
dependencies: []
---

# Image Calculator test improvements

## Problem Statement

Multiple review agents identified test gaps and test hygiene issues in the Image Calculator test suite.

## Findings

### 1. Monkey-patching store with _test_fov_id (kieran-python-reviewer #4)
- **Location**: `tests/test_plugins/test_image_calculator.py:51`
- `store._test_fov_id = fov_id` attaches a private attribute to a production object.
- Fix: Return `tuple[ExperimentStore, int]` from the helper function.

### 2. Store cleanup not guaranteed on assertion failure (kieran-python-reviewer #10)
- **Location**: All integration tests call `store.close()` at the end.
- If an assertion fails before `store.close()`, the store leaks.
- Fix: Use a pytest fixture with `yield` or `try/finally`.

### 3. Missing test coverage (kieran-python-reviewer, performance-oracle)
- No test for float32 input dtype (only uint8 and uint16 tested)
- No test for channel_a not found (only channel_b not found tested)
- No integration test for two-channel bitwise operations
- No test for plugin-level operation validation RuntimeError

## Proposed Solutions

### Option A: All improvements together (Recommended)

1. Change helper to return `(store, fov_id)` tuple
2. Convert to pytest fixture with yield for cleanup
3. Add the 4 missing test cases

- **Effort**: Small
- **Risk**: None

## Acceptance Criteria

- [ ] Helper returns tuple instead of monkey-patching
- [ ] Store cleanup uses fixture or try/finally
- [ ] Test for float32 input dtype added
- [ ] Test for channel_a not found added
- [ ] Test for two-channel bitwise op added

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-03 | Created from code review | Return test data from helpers, don't attach to production objects |
