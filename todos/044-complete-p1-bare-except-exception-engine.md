---
status: complete
priority: p1
issue_id: "044"
tags: [code-review, segment, error-handling]
dependencies: []
---

# Bare `except Exception` in Engine Swallows Critical Errors

## Problem Statement

`SegmentationEngine.run()` (line 139-143 of `_engine.py`) catches `Exception` for per-region error handling, which includes `MemoryError`, `sqlite3.IntegrityError`, and other critical errors. A database integrity error during `add_cells()` or `write_labels()` is silently appended to `warnings` as a string, and the engine continues, leaving the experiment in a potentially inconsistent state. No traceback is logged.

## Findings

- **File:** `src/percell3/segment/_engine.py:139-143`
- `MemoryError` is caught and treated as a warning — engine continues allocating
- `sqlite3.IntegrityError` is caught — DB may be in inconsistent state
- No traceback logged anywhere — debugging is impossible
- Caller has no way to distinguish between "0 cells" warnings and "segmentation crashed" errors

## Proposed Solutions

### Option 1 (Recommended): Log traceback and narrow the catch

```python
import logging
logger = logging.getLogger(__name__)

except (RuntimeError, ValueError, OSError) as exc:
    logger.warning("Segmentation failed for %s", region_info.name, exc_info=True)
    warnings.append(f"{region_info.name}: segmentation failed — {exc}")
```

### Option 2: Keep broad catch but add re-raise conditions

```python
except Exception as exc:
    if isinstance(exc, (MemoryError, SystemExit)):
        raise
    logger.warning(..., exc_info=True)
    warnings.append(...)
```

## Acceptance Criteria

- [ ] Critical errors (`MemoryError`, `IntegrityError`) not silently swallowed
- [ ] Traceback logged for debugging
- [ ] Test verifying per-region error handling (currently missing)

## Work Log

### 2026-02-16 — Code Review Discovery
Identified by kieran-python-reviewer. Silent error swallowing blocks debugging and risks data corruption.
