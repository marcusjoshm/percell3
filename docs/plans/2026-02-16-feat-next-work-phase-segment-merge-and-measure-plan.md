---
title: "Next Work Phase: Segment P1 Fixes, Merge to Main, Measure Module"
type: feat
date: 2026-02-16
---

# Next Work Phase: Segment P1 Fixes, Merge to Main, Measure Module

## Overview

This plan covers the remaining work to complete the segment module, merge it to
`main`, clean up stale branches, and begin the measure module. There are 4 phases:

| Phase | Description | Branch | Effort |
|-------|-------------|--------|--------|
| **A** | Fix 3 remaining P1 issues on segment module | `feat/segment-module-v2` | ~1 hour |
| **B** | Merge to `main`, delete stale branches | `main` | ~15 min |
| **C** | Segment CLI integration (replace stub) | `feat/segment-cli` | ~2 hours |
| **D** | Implement Module 4: Measure | `feat/measure-module` | ~4 hours |

## Current State

**Branch:** `feat/segment-module-v2` (2 commits ahead of `main`)

**Modules completed:** core, io, workflow, cli, segment (domain logic only)

**Tests:** 438 passing

**Completed P1 fixes (commit `f4db399`):**
- 033: Cellpose 4.0 API `getattr()` fallback
- 034: Private `store._conn` removed, public method added
- 035: Pickle deserialization warning on `import_cellpose_seg`

**Remaining P1 issues (3):**
- 045: Unvalidated model name -> arbitrary code execution
- 043: ROI import writes before validation -> orphaned data
- 044: Bare `except Exception` swallows critical errors

**Deferred (not a merge blocker):**
- 042: `--gpu` flag silently ignored — the CLI `segment` command is still a stub on `main`, so this is a Phase C concern

---

## Phase A: Fix Remaining P1 Issues

**Branch:** `feat/segment-module-v2`
**Commit strategy:** One commit per fix for clean bisection

### A1. Fix todo-045 — Model name validation (security)

**File:** `src/percell3/segment/cellpose_adapter.py`

**Approach:** Allowlist validation at the adapter level (not just CLI) so the Python
API is also protected. Use Option 1 from the todo: hardcoded allowlist of known
Cellpose built-in models.

```python
# cellpose_adapter.py
KNOWN_CELLPOSE_MODELS = frozenset({
    "cyto", "cyto2", "cyto3", "nuclei",
    "tissuenet", "livecell", "tissuenet_cp3", "livecell_cp3",
    "deepbacs_cp3", "cyto2_cp3", "yeast_PhC_cp3", "yeast_BF_cp3",
    "bact_phase_cp3", "bact_fluor_cp3", "plant_cp3",
})

def _get_model(self, model_name: str, gpu: bool):
    if model_name not in KNOWN_CELLPOSE_MODELS:
        raise ValueError(
            f"Unknown model {model_name!r}. "
            f"Known models: {sorted(KNOWN_CELLPOSE_MODELS)}"
        )
    # ... existing logic
```

**Test:** `test_cellpose_adapter.py`
```python
def test_path_model_name_rejected():
    adapter = CellposeAdapter()
    with pytest.raises(ValueError, match="Unknown model"):
        adapter._get_model("../evil", gpu=False)
```

### A2. Fix todo-043 — Validate region before writes (data integrity)

**File:** `src/percell3/segment/roi_import.py`

**Approach:** Move region lookup to the top of both `import_labels()` and
`import_cellpose_seg()`, before `add_segmentation_run()` or `write_labels()`.
If the region doesn't exist, raise `ValueError` with no side effects.

**Before:**
```python
def import_labels(self, labels, store, region, condition, ...):
    run_id = store.add_segmentation_run(...)     # DB write
    store.write_labels(...)                       # Zarr write
    region_info = ...                             # validate AFTER writes
```

**After:**
```python
def import_labels(self, labels, store, region, condition, ...):
    # Validate region exists FIRST
    regions = store.get_regions(condition=condition)
    target = next((r for r in regions if r.name == region), None)
    if target is None:
        raise ValueError(f"Region {region!r} not found in condition {condition!r}")

    run_id = store.add_segmentation_run(...)     # now safe to write
    store.write_labels(...)
```

Apply the same pattern to `import_cellpose_seg()`.

**Test:** `test_roi_import.py`
```python
def test_import_labels_invalid_region_no_orphaned_data(store):
    """Failed import should leave no orphaned DB records or Zarr data."""
    with pytest.raises(ValueError, match="not found"):
        importer.import_labels(labels, store, "nonexistent", "control", ...)
    # Verify no segmentation runs were created
    assert store.get_segmentation_runs() == []
```

### A3. Fix todo-044 — Narrow exception handling (reliability)

**File:** `src/percell3/segment/_engine.py`

**Approach:** Use Option 2 (keep broad catch but re-raise critical errors). This is
safer than narrowing to specific types, because we don't know all exception types
Cellpose might raise. Add `logging.getLogger(__name__)` and log tracebacks.

```python
import logging
logger = logging.getLogger(__name__)

# In the per-region loop:
except Exception as exc:
    if isinstance(exc, (MemoryError, KeyboardInterrupt, SystemExit)):
        raise
    logger.warning(
        "Segmentation failed for region %s: %s",
        region_info.name, exc, exc_info=True,
    )
    warnings.append(f"{region_info.name}: segmentation failed — {exc}")
```

**Test:** `test_engine.py`
```python
def test_memory_error_propagates(mock_segmenter):
    """MemoryError should not be caught by per-region handler."""
    mock_segmenter.segment.side_effect = MemoryError("out of memory")
    with pytest.raises(MemoryError):
        engine.run(store, channel="DAPI")

def test_region_error_continues(mock_segmenter):
    """ValueError on one region should not stop other regions."""
    mock_segmenter.segment.side_effect = [ValueError("bad"), good_mask]
    result = engine.run(store, channel="DAPI")
    assert len(result.warnings) == 1
    assert result.total_cells > 0  # second region succeeded
```

### A4. Run full test suite

```bash
pytest tests/ -v
```

All 438+ tests must pass.

---

## Phase B: Merge to Main and Clean Up Branches

### B1. Pre-merge checklist

- [x] All P1 fixes from Phase A committed and tested
- [x] `feat/segment-module-v2` rebased on latest `main` (or merged forward)
- [x] Full test suite passes: `pytest tests/ -v`
- [ ] Untracked files decision: commit todos and docs, or `.gitignore`

### B2. Merge strategy

Use a merge commit (not squash) to preserve individual fix commits for bisection:

```bash
git checkout main
git merge feat/segment-module-v2 --no-ff
```

The merge commit message should summarize the branch:

```
Merge feat/segment-module-v2: headless segmentation engine + P1 fixes

Phases 1-5 of the segmentation module:
- BaseSegmenter ABC + CellposeAdapter (3.x/4.x compatible)
- LabelProcessor for label image processing
- SegmentationEngine for orchestrating region-by-region segmentation
- RoiImporter for importing external label/ROI data
- P1 fixes: model name validation, early region validation,
  exception handling, Cellpose 4.0 compat, private API removal
```

### B3. Delete stale branches

Verify each is fully merged before deletion:

```bash
# Verify merged status
git branch --merged main

# Delete local branches (only if listed as merged)
git branch -d feat/cli-module
git branch -d feat/io-module
git branch -d refactor/core-p2-p3-review-fixes
git branch -d feat/segment-module          # superseded by v2
git branch -d feat/segment-module-v2       # just merged
```

**Do NOT delete branches with unmerged commits.** If `git branch -d` refuses
(lowercase `-d`), investigate before using `-D`.

### B4. Post-merge verification

```bash
git checkout main
pytest tests/ -v
```

---

## Phase C: Segment CLI Integration

**Branch:** `feat/segment-cli` (created from `main` after Phase B merge)

This is Phase 6 of the segmentation plan — wiring the domain engine to the CLI.

### C1. Create `src/percell3/cli/segment.py`

Replace the stub in `stubs.py` with a real implementation.

**CLI arguments:**
- `--channel` (required): Channel name for segmentation
- `--model` (default: `cyto3`): `click.Choice(KNOWN_CELLPOSE_MODELS)`
- `--diameter` (default: `None`): Estimated cell diameter in pixels
- `--regions` (optional): Comma-separated region filter
- `--condition` (optional): Condition filter

**Do NOT expose `--gpu` flag yet.** Remove the existing stub's `--gpu/--no-gpu`
flag. Add it back when todo-036 (engine params gap) is resolved. This addresses
todo-042.

### C2. Progress display

Use Rich progress bar via `SegmentationEngine.run(progress_callback=...)`:

```python
from rich.progress import Progress

with Progress() as progress:
    task = progress.add_task("Segmenting...", total=None)

    def on_progress(current, total, region_name):
        progress.update(task, total=total, completed=current,
                       description=f"Segmenting {region_name}")

    result = engine.run(store, channel=channel, model=model,
                       diameter=diameter, progress_callback=on_progress)
```

### C3. Error handling

- Catch `ChannelNotFoundError`, `ValueError` → pretty-print with `rich.console`
- Let unexpected exceptions propagate with full traceback

### C4. Update `main.py`

Remove import from `stubs.py`, import from `segment.py` instead. Keep stubs
for `measure` and `threshold` commands.

### C5. Merge `feat/segment-cli` to `main`

Same merge commit strategy as Phase B.

---

## Phase D: Implement Module 4 — Measure

**Branch:** `feat/measure-module` (created from `main` after Phase C merge)

### D1. Files to create

```
src/percell3/measure/
├── __init__.py              # Public API exports
├── measurer.py              # Measurer class — per-region measurement
├── metrics.py               # MetricRegistry + built-in metric functions
├── thresholding.py          # ThresholdEngine — Otsu, adaptive, manual
└── batch.py                 # BatchMeasurer — all regions x all channels
```

### D2. Implementation order

1. **`metrics.py`** — MetricRegistry with 8 built-in metrics (mean, max, min,
   integrated, std, median, area, positive_fraction). Pure functions, no store
   dependency. Easy to test in isolation.

2. **`measurer.py`** — `Measurer` class with `measure_region()` and
   `measure_cells()`. Reads labels + channel images from store, computes metrics
   per cell, writes MeasurementRecords via `store.add_measurements()`.

3. **`thresholding.py`** — `ThresholdEngine` with Otsu, adaptive, manual,
   triangle, Li methods via scikit-image. Writes binary masks to `masks.zarr`.

4. **`batch.py`** — `BatchMeasurer` with `measure_experiment()` for all
   regions x all channels. Progress callback support.

### D3. Key design decisions

- **Bounding box optimization:** Use cell bbox from the cells table to crop
  images before computing metrics (avoid full-image processing per cell).
- **Bulk insert:** Use `store.add_measurements()` with batched records, not
  one-by-one insertion.
- **Metric function signature:** `(channel_image_crop, cell_binary_mask) -> float`
- **Only use ExperimentStore public API.** No `store._conn`, no `queries` import.
  (Lesson from todo-034.)

### D4. Acceptance criteria (from spec)

- [x] Can measure mean/max/integrated intensity for any channel using existing labels
- [x] Can measure a channel NOT used for segmentation
- [x] Measurements stored in SQLite via `store.add_measurements()`
- [x] Otsu thresholding produces binary mask in `masks.zarr`
- [x] Batch mode measures all cells x all channels efficiently
- [x] `get_measurement_pivot()` returns clean DataFrame

### D5. Merge `feat/measure-module` to `main`

Same strategy: merge commit with `--no-ff`, verify all tests pass.

---

## Pending P2/P3 Items (Not in Scope — Track for Later)

These items are acknowledged but **not planned for this work phase**:

**Segment P2 (batch after merge):**
- 036: Engine params gap (expose all SegmentationParams)
- 037: Duplicated roi_import logic
- 038: Mutable list in frozen dataclass
- 039: Row-by-row cell INSERT performance
- 046: SegmentationResult lacks per-region stats
- 047: SQLite WAL synchronous=NORMAL
- 048: Fragile hand-written `to_dict()`

**Segment P3:**
- 040: `segment_batch()` dead code (YAGNI)
- 041: Stateless classes could be functions
- 049: Misleading lazy import comment
- 050: Unnecessary float64 wrapping
- 051: Missing segment CLI tests

**CLI P2/P3 (already on main):**
- 016-025: Various CLI review findings

---

## Branch Lifecycle Summary

```
main ─────────────┬─── Phase B merge ──┬─── Phase C merge ──┬─── Phase D merge ──→
                  │                     │                     │
feat/segment-v2 ──┤ (Phase A fixes)    │                     │
                  │                     │                     │
                  ×  (delete after B)   │                     │
                                        │                     │
feat/segment-cli ─────────────────────── ┤ (Phase C work)     │
                                        │                     │
                                        ×  (delete after C)   │
                                                              │
feat/measure-module ──────────────────────────────────────────┤ (Phase D work)
                                                              │
                                                              × (delete after D)
```

**Branches to delete immediately (Phase B):**
- `feat/cli-module` (already merged)
- `feat/io-module` (already merged)
- `refactor/core-p2-p3-review-fixes` (already merged)
- `feat/segment-module` (superseded by v2)

## References

- [Segment Module Plan (headless)](../plans/2026-02-13-feat-segmentation-engine-headless-plan.md)
- [Measure Module Spec](../04-measure/spec.md)
- [Measure Module CLAUDE.md](../04-measure/CLAUDE.md)
- [Cellpose 4.0 Solution Doc](../solutions/integration-issues/cellpose-4-0-api-breaking-change.md)
- [Architecture Encapsulation Fix](../solutions/architecture-decisions/segment-module-private-api-encapsulation-fix.md)
