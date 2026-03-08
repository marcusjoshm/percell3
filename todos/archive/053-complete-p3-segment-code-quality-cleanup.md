---
status: pending
priority: p3
issue_id: "053"
tags: [code-review, segment, code-quality]
dependencies: []
---

# Segment Module Small Code Quality Fixes (Bundle)

## Problem Statement

Several minor code quality issues identified during the post-merge review of the segment module. None are bugs, but they reduce clarity and maintainability.

## Findings

### 1. Unused `import math` in base_segmenter.py

**File:** `src/percell3/segment/base_segmenter.py:6`

`math` is imported but never used in this file. The `math.pi` usage is in `label_processor.py`.

**Fix:** Remove line 6.

### 2. Dead `isinstance` check for KeyboardInterrupt/SystemExit in _engine.py

**File:** `src/percell3/segment/_engine.py:143`

```python
except Exception as exc:
    if isinstance(exc, (MemoryError, KeyboardInterrupt, SystemExit)):
        raise
```

`KeyboardInterrupt` and `SystemExit` inherit from `BaseException`, not `Exception`. They can never be caught by `except Exception`. The isinstance check for those two is dead code — only `MemoryError` (which IS a subclass of `Exception`) is actually re-raised.

**Fix:** Remove `KeyboardInterrupt, SystemExit` from the isinstance tuple, or restructure:
```python
except MemoryError:
    raise
except Exception as exc:
    logger.warning(...)
```

### 3. Logger placement between imports in _engine.py

**File:** `src/percell3/segment/_engine.py:9-11`

`logger = logging.getLogger(__name__)` is placed between import groups, violating PEP 8 import ordering. Move it after all imports.

### 4. Missing `cellprob_threshold` range validation

**File:** `src/percell3/segment/base_segmenter.py:39-52`

`flow_threshold` is validated (0-3 range) but `cellprob_threshold` (-6 to 6 for Cellpose) has no range check. A user can pass `cellprob_threshold=100` without error.

**Fix:** Add validation:
```python
if not (-6 <= self.cellprob_threshold <= 6):
    raise ValueError(
        f"cellprob_threshold must be between -6 and 6, got {self.cellprob_threshold}"
    )
```

### 5. Fixture return type annotations

**Files:** `tests/test_segment/test_engine.py:46`, `tests/test_segment/test_roi_import.py:16`

Yield fixtures annotated as `-> ExperimentStore` should be `-> Iterator[ExperimentStore]` for type checker correctness.

## Acceptance Criteria

- [ ] No unused imports in segment module
- [ ] Exception handling in _engine.py correctly documents what is caught
- [ ] Logger placement follows PEP 8
- [ ] cellprob_threshold has range validation
- [ ] All tests pass

## Work Log

### 2026-02-16 — Code Review Discovery
Identified by kieran-python-reviewer, code-simplicity-reviewer, and security-sentinel. Bundle of 5 minor issues.
