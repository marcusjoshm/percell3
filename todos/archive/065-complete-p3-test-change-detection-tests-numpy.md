---
status: complete
priority: p3
issue_id: "065"
tags: [code-review, test-quality, yagni]
dependencies: []
---

# TestChangeDetection Tests NumPy, Not PerCell Code

## Problem Statement
The `TestChangeDetection` class in `tests/test_segment/test_viewer.py` tests that `np.array_equal()` returns True/False for identical/different arrays. This is testing numpy's built-in behavior, not any PerCell code. These ~17 lines add no value and could be removed or replaced with tests that exercise the actual change detection logic in the viewer.

## Findings
- **File:** `tests/test_segment/test_viewer.py` — `TestChangeDetection` class
- Flagged by: code-simplicity-reviewer
- Tests like `assert np.array_equal(a, a.copy()) is True` verify numpy, not PerCell
- ~17 lines of test code with no coverage value

## Proposed Solutions
### Option 1 (Recommended): Replace with integration tests
Replace with tests that exercise the actual save-back decision logic (e.g., "when labels unchanged, no run is created").

### Option 2: Delete entirely
Remove the test class. The change detection is trivial enough to not need dedicated tests.

## Acceptance Criteria
- [ ] Tests exercise PerCell logic, not numpy builtins
