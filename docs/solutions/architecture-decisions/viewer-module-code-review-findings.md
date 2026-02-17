---
title: "Code Review: Napari Viewer Module (Module 3b) — 14 Findings"
date: 2026-02-16
module:
  - segment
  - viewer
  - cli
severity:
  - P1
  - P2
  - P3
tags:
  - code-review
  - napari-viewer
  - error-handling
  - data-integrity
  - performance
  - agent-native
  - api-design
problem_type: code-review
review_agents:
  - kieran-python-reviewer
  - code-simplicity-reviewer
  - security-sentinel
  - performance-oracle
  - agent-native-reviewer
  - learnings-researcher
branch: feat/napari-viewer
files_reviewed: 11
lines_added: 1281
---

# Code Review: Napari Viewer Module (Module 3b) — 14 Findings

## Problem Statement

A comprehensive code review was performed on the napari viewer integration for PerCell 3 (Module 3b, branch `feat/napari-viewer`). The module adds interactive segmentation label viewing and editing via napari, with automatic save-back to ExperimentStore. The review covered 11 files (~1281 lines added) across the viewer subpackage, CLI command, and interactive menu integration.

The review discovered **14 findings**: 3 P1 critical (including a data-loss vulnerability), 6 P2 important, and 5 P3 nice-to-have improvements.

## Review Methodology

Six specialized review agents analyzed the codebase in parallel:

1. **kieran-python-reviewer** — Python code quality, idioms, type safety
2. **code-simplicity-reviewer** — Dead code, redundancy, YAGNI violations
3. **security-sentinel** — Error handling, data integrity, attack surface
4. **performance-oracle** — Memory usage, algorithmic complexity, scalability
5. **agent-native-reviewer** — Headless access, API parity, programmatic control
6. **learnings-researcher** — Cross-reference with past solutions in `docs/solutions/`

Findings were deduplicated across agents (many issues were independently flagged by 4-6 agents, confirming their significance) and prioritized by severity.

## Key Root Causes

### 1. Dict Key Mismatch + Bare Exception = Silent Label Loss (P1-056 + P1-057)

The most critical finding is a **two-bug combination** that causes silent data loss:

**Bug A — Wrong dict key (todo-057):**
```python
# src/percell3/segment/viewer/_viewer.py:193
runs = store.get_segmentation_runs()
if runs:
    latest = max(runs, key=lambda r: r["id"])
    seg_channel = latest.get("channel_name")  # BUG: key is "channel", not "channel_name"
```

The SQL query in `queries.py:301` aliases the column as `seg_channel AS channel`, but the viewer code looks for `"channel_name"`. Result: `seg_channel` is always `None`.

**Bug B — Bare exception swallows the failure (todo-056):**
```python
# src/percell3/segment/viewer/_viewer.py:197-221
try:
    labels = store.read_labels(region, condition)
    original_labels = labels.copy()
    viewer.add_labels(labels, name="segmentation", opacity=0.5)
except Exception:  # Catches EVERYTHING — MemoryError, PermissionError, bugs
    # Falls through to empty labels silently
    empty = np.zeros(label_shape, dtype=np.int32)
    viewer.add_labels(empty, name="segmentation", opacity=0.5)
```

**The data-loss scenario:**
1. User opens viewer with existing labels
2. `get("channel_name")` returns `None` → `read_labels()` fails
3. Bare `except Exception` silently falls through to empty canvas
4. User paints some cells, closes napari
5. Save-back overwrites real labels with the new (near-empty) data
6. Original labels are gone

**Fix:** Change `"channel_name"` to `"channel"`. Narrow the except to `KeyError` only.

### 2. Private Save Function — No Headless/Agent Access (P1-058)

`_save_edited_labels()` is the only code path for persisting edited labels, but it's private and only callable from within `_launch()` after napari closes. No public API or CLI command exists for headless label saving. Additionally, `RoiImporter` duplicates the same pipeline (todo-064), creating divergence risk.

**Fix:** Extract a public `save_labels()` function. Wire both viewer and RoiImporter to use it. Add a `percell3 import-labels` CLI command.

### 3. Performance: Double Label Materialization (P2-062)

For change detection, the label array is loaded into memory (~400MB for 10K×10K int32), then copied (~400MB). Total: ~800MB just for labels. Additionally, `np.unique()` (O(n log n)) is called redundantly when `cell_count` is already available (todo-061).

**Fix:** Use hash-based change detection (32 bytes instead of 400MB copy). Remove `np.unique()`, use `cell_count`.

## Findings Summary

### P1 — Critical (Blocks Merge)

| ID | Issue | File | Agent Consensus |
|---|---|---|---|
| 056 | Bare `except Exception` swallows real errors → silent data loss | `_viewer.py:197` | 6/6 agents |
| 057 | Dict key `"channel_name"` should be `"channel"` → labels never load | `_viewer.py:193` | 6/6 agents |
| 058 | `_save_edited_labels()` private → no headless/agent access | `_viewer.py:225` | 6/6 agents |

### P2 — Important (Should Fix)

| ID | Issue | File | Impact |
|---|---|---|---|
| 059 | Unused `import json` | `_viewer.py:5` | Dead code |
| 060 | Display check misses `WAYLAND_DISPLAY` | `_viewer.py:81` | Wayland Linux fails |
| 061 | `np.unique()` O(n log n), redundant with `cell_count` | `_viewer.py:276` | 2-5s on large images |
| 062 | Double label array copy for change detection | `_viewer.py:199` | ~800MB for 10K×10K |
| 063 | `viewer: object` type annotation loses checking | `_viewer.py:149` | No mypy coverage |
| 064 | Duplicate label-save logic (viewer vs RoiImporter) | `_viewer.py` + `roi_import.py` | Divergence risk |

### P3 — Nice-to-Have

| ID | Issue | Rationale |
|---|---|---|
| 065 | `TestChangeDetection` tests numpy, not PerCell | 17 lines of no-value tests |
| 066 | `_NAME_TO_COLORMAP` over-populated | YAGNI — only DAPI/GFP/RFP used |
| 067 | `_default_contrast_limits` duplicates napari defaults | napari auto-computes this |
| 068 | Redundant napari availability checks (3 locations) | Consolidate to one |
| 069 | Magic 512×512 fallback shape | Should error, not guess |

## Prevention Strategies

### 1. Bare `except Exception` — Recurring Anti-Pattern

Previously found in the segment engine (todo-044), now found again in the viewer (todo-056). This is a recurring pattern in the codebase.

**Detection:**
```bash
# Find all bare except Exception patterns
rg 'except Exception:' --type py src/percell3/
# Should return 0 results after fixes
```

**Rule:** Only catch specific exception types. If unsure what to catch, let it propagate. Always log caught exceptions at WARNING level.

### 2. SQL Alias / Dict Key Mismatch — No Type Safety

The SQL query uses `AS channel` but consuming code uses `.get("channel_name")`. There is no type safety between SQL result dicts and Python consumers.

**Detection:**
```bash
# Compare SQL aliases with consuming .get() calls
rg 'AS\s+(\w+)' --type py src/percell3/core/queries.py
rg '\.get\("' --type py src/percell3/segment/viewer/
```

**Rule:** Consider dataclasses or `_row_to_Model()` converter functions for SQL results instead of raw dicts. Direct `dict["key"]` access (which raises KeyError on mismatch) is safer than `.get()` (which silently returns None).

### 3. Private Functions Blocking Agent Access — Recurring Pattern

Previously found with `store._conn` (todo-034), now with `_save_edited_labels()` (todo-058).

**Detection:**
```bash
# Find private functions imported in tests (API incompleteness signal)
rg 'from percell3.*import _' tests/ --type py
# Find duplicate multi-step pipelines
rg 'write_labels.*extract_cells\|extract_cells.*write_labels' --type py src/
```

**Rule:** If two modules need the same logic, or a test imports `_private` functions, the API is incomplete. Extract to a public abstraction.

### 4. YAGNI Violations

**Detection:**
```bash
# Find large constant dicts (potential YAGNI)
rg '_TO_\w+\s*[:=]\s*\{' --type py src/
```

**Rule:** Start minimal. Add mappings/fallbacks when a user reports a real need, not speculatively.

## Review Checklist for Future Viewer PRs

- [ ] No bare `except Exception:` — catch specific types only
- [ ] Dict keys match SQL aliases — verify against `queries.py`
- [ ] All business logic is in public functions — agents can call it
- [ ] No duplicate pipelines — shared logic in one place
- [ ] napari availability checked in one location only
- [ ] Memory-conscious for large images — no unnecessary copies
- [ ] Wayland and macOS headless cases handled
- [ ] Tests exercise PerCell code, not third-party library behavior

## Cross-References

- **Past: Bare except in engine** — `todos/044-complete-p1-bare-except-exception-engine.md`
- **Past: Private API access** — `docs/solutions/architecture-decisions/segment-module-private-api-encapsulation-fix.md`
- **Past: CLI review patterns** — `docs/solutions/architecture-decisions/cli-module-code-review-findings.md`
- **Past: Cellpose 4.0 compat** — `docs/solutions/integration-issues/cellpose-4-0-api-breaking-change.md`
- **Past: Core security fixes** — `docs/solutions/security-issues/core-module-p1-security-correctness-fixes.md`
- **Current todos:** `todos/056-pending-p1-*` through `todos/069-pending-p3-*`

## Resources

- **Branch:** `feat/napari-viewer`
- **Plan:** `docs/plans/2026-02-16-feat-segment-module-3b-napari-viewer-plan.md`
- **Primary file:** `src/percell3/segment/viewer/_viewer.py`
- **SQL layer:** `src/percell3/core/queries.py:298-312`
