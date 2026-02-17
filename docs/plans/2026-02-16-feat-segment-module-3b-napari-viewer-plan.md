---
title: "feat: Segment Module 3b — napari Viewer Integration"
type: feat
date: 2026-02-16
module: segment
---

# Segment Module 3b — napari Viewer Integration

## Overview

Build the napari-based viewer/editor for PerCell 3 — the GUI counterpart to the
headless segmentation engine (Module 3a). This module launches napari pre-loaded
with experiment data from OME-Zarr, supports manual label editing with save-back
to ExperimentStore, and integrates with the cellpose-napari plugin for interactive
re-segmentation.

napari is an **optional dependency** (`pip install percell3[napari]`). Core
functionality (headless segmentation, measurement, export) works without it.

## Problem Statement / Motivation

Module 3a provides headless segmentation via `percell3 segment`. But microscopy
users need to:

1. **Visualize** segmentation results overlaid on channel images
2. **Correct** segmentation errors — merge split cells, delete debris, paint
   missed cells
3. **Re-segment interactively** — tune Cellpose parameters with visual feedback
4. **Multi-channel overlay** — view DAPI + GFP + labels simultaneously

Without a viewer, users must export TIFFs, open in Fiji/napari manually, edit,
export back, and re-import — a fragile multi-step workflow that PerCell 3 should
automate.

## Dependencies & Prerequisites

- **Module 3a (Segment Engine)**: Complete. Provides `SegmentationEngine`,
  `LabelProcessor.extract_cells()`, `RoiImporter`, `BaseSegmenter` ABC.
- **Module 1 (Core)**: Complete. ExperimentStore provides `read_image()`,
  `read_image_numpy()`, `read_labels()`, `write_labels()`, `add_cells()`,
  `add_segmentation_run()`, `get_regions()`, `get_channels()`.
- **napari>=0.5,<1.0**: Optional. Current stable: 0.7.0 (Jan 2026).
- **napari-ome-zarr>=0.6**: For loading OME-Zarr data (optional, not strictly
  required since we load via ExperimentStore API).
- **cellpose-napari**: Separate install, detected at runtime. Not bundled.

No dependency on IO, CLI, or Workflow modules in domain code. CLI integration is
in the CLI module.

## Technical Approach

### Architecture

```
percell3.segment.viewer (NEW — Module 3b)
    │
    ├── launcher.py      ← NapariLauncher: load experiment → napari
    ├── callbacks.py     ← Save-back: napari labels → ExperimentStore
    └── __init__.py      ← Public API + availability check
    │
    │  uses ↓
    │
percell3.segment (Module 3a — existing)
    ├── label_processor.py   ← extract_cells() for re-extraction
    ├── roi_import.py        ← RoiImporter for save-back pipeline
    └── base_segmenter.py    ← SegmentationParams (reference)
    │
    │  uses ↓
    │
percell3.core (Module 1 — existing)
    └── ExperimentStore      ← All reads/writes go through public API
```

### Key Design Decisions

1. **Save on close**: When napari closes, compare label data to original. If
   changed, save automatically. Print confirmation to terminal. This follows the
   blocking `napari.run()` pattern — script resumes after viewer closes.

2. **One region per session**: Initial implementation loads one region at a time.
   User specifies `--region` on CLI. Multi-region switching is a future
   enhancement (Phase 5 stretch goal).

3. **All channels loaded**: All experiment channels loaded as separate napari
   image layers with sensible default colormaps. Labels loaded as label layer
   on top.

4. **Re-extract all cells**: When saving edited labels, re-extract properties
   for all cells in the region using `extract_cells()`. Simpler than diffing
   individual cells, and consistent with headless segmentation behavior.

5. **New segmentation run**: Saved edits create a new `segmentation_run` with
   `model_name="napari_edit"`. Old runs preserved (immutable history).

6. **cellpose-napari is user-managed**: PerCell 3 doesn't programmatically
   configure the plugin. User runs it via napari's plugin menu. We import the
   resulting label layer on save.

7. **ExperimentStore public API only**: No `store._conn`, no `queries` import.
   Lesson from todo-034 (private API encapsulation fix).

### File Structure

```
src/percell3/segment/
├── viewer/                      # NEW: napari integration subpackage
│   ├── __init__.py              # Public API: launch_viewer, NAPARI_AVAILABLE
│   ├── launcher.py              # NapariLauncher class
│   └── callbacks.py             # Label save-back logic
├── __init__.py                  # MODIFY: re-export viewer API
├── _engine.py                   # (existing)
├── base_segmenter.py            # (existing)
├── cellpose_adapter.py          # (existing)
├── label_processor.py           # (existing)
└── roi_import.py                # (existing)

src/percell3/cli/
├── view.py                      # NEW: `percell3 view` command
├── main.py                      # MODIFY: register view command
└── menu.py                      # MODIFY: add "View in napari" menu item

tests/test_segment/
├── test_viewer/                 # NEW: viewer tests
│   ├── __init__.py
│   ├── conftest.py              # napari fixtures, skip if not installed
│   ├── test_launcher.py         # Viewer launch tests
│   └── test_callbacks.py        # Save-back tests
└── (existing test files)

tests/test_cli/
└── test_view.py                 # NEW: CLI view command tests
```

## Implementation Phases

### Phase 1: Foundation — Availability Check + Launcher

**Files**: `viewer/__init__.py`, `viewer/launcher.py`

- [ ] Create `viewer/__init__.py` with napari availability check:
  ```python
  # viewer/__init__.py
  try:
      import napari  # noqa: F401
      NAPARI_AVAILABLE = True
  except ImportError:
      NAPARI_AVAILABLE = False

  def _require_napari() -> None:
      if not NAPARI_AVAILABLE:
          raise ImportError(
              "napari is required for the viewer. "
              "Install with: pip install 'percell3[napari]'"
          )
  ```
- [ ] Create `NapariLauncher` class in `launcher.py`:
  ```python
  class NapariLauncher:
      def launch(
          self,
          store: ExperimentStore,
          region: str,
          condition: str,
          channels: list[str] | None = None,
      ) -> ViewerResult:
          """Launch napari with experiment data. Blocks until viewer closes."""
  ```
- [ ] Load all channels as image layers (dask arrays for lazy loading)
- [ ] Load existing labels as label layer (if segmentation exists)
- [ ] Apply default colormaps: DAPI=blue, GFP=green, RFP=red, others=gray
- [ ] Set viewer title: `"PerCell 3 — {region} ({condition})"`
- [ ] Call `napari.run()` (blocking)
- [ ] Return `ViewerResult` with info about what happened
- [ ] Detect headless environment before launching:
  ```python
  import os
  if not os.environ.get("DISPLAY") and sys.platform != "darwin":
      raise RuntimeError(
          "napari requires a display server. "
          "Use X11 forwarding or run on a local machine."
      )
  ```

**Tests** (`test_launcher.py`):
- [ ] `NAPARI_AVAILABLE` is True when napari installed
- [ ] `_require_napari()` raises ImportError when napari missing (mock)
- [ ] Launcher loads correct number of image layers
- [ ] Launcher loads label layer when segmentation exists
- [ ] Launcher skips label layer when no segmentation exists
- [ ] Default colormaps applied correctly

Note: Tests use `make_napari_viewer(show=False)` fixture for headless testing.
Guard with `pytest.importorskip("napari")`.

---

### Phase 2: Label Save-Back — Edit and Persist

**File**: `viewer/callbacks.py`

- [ ] Create `save_edited_labels()` function:
  ```python
  def save_edited_labels(
      store: ExperimentStore,
      region: str,
      condition: str,
      original_labels: np.ndarray | None,
      edited_labels: np.ndarray,
      channel: str = "manual",
  ) -> int | None:
      """Save edited labels back to ExperimentStore.

      Compares edited_labels to original_labels. If changed:
      1. Create segmentation run (model_name="napari_edit")
      2. Write labels to zarr
      3. Re-extract cell properties via extract_cells()
      4. Insert cells into DB
      5. Return run_id

      Returns None if labels unchanged.
      """
  ```
- [ ] Integrate into launcher: after `napari.run()` returns, compare labels
- [ ] Use `np.array_equal()` for change detection
- [ ] Reuse `extract_cells()` from `label_processor.py` for cell property extraction
- [ ] Print save confirmation to terminal via `rich.console`
- [ ] Handle edge cases:
  - All labels erased (0 cells) — save empty labels, warn
  - Labels unchanged — skip save, print "No changes detected"
  - ExperimentStore closed/corrupted — catch and report error

**Tests** (`test_callbacks.py`):
- [ ] Modified labels trigger save, return run_id
- [ ] Unchanged labels return None (no DB writes)
- [ ] Saved labels round-trip: read back from zarr matches edited array
- [ ] Cell count in DB matches unique labels (excluding 0)
- [ ] Cell properties (area, centroid) are correct after re-extraction
- [ ] Empty labels (all erased): run created with 0 cells + warning

---

### Phase 3: CLI + Menu Integration

**Files**: `cli/view.py`, `cli/main.py`, `cli/menu.py`

- [ ] Create `percell3 view` Click command:
  ```python
  @click.command()
  @click.option("-e", "--experiment", required=True, type=click.Path(exists=True))
  @click.option("-r", "--region", required=True, help="Region name to view.")
  @click.option("--condition", default=None, help="Condition filter.")
  @click.option("--channels", default=None, help="Comma-separated channels to load.")
  @error_handler
  def view(experiment, region, condition, channels):
      """Launch napari to view and edit segmentation labels."""
  ```
- [ ] Handle `--condition` default: if experiment has one condition, use it
  automatically. If multiple, require `--condition` or show choices.
- [ ] Register in `main.py`: `cli.add_command(view)`
- [ ] Remove "coming soon" for relevant menu items in `menu.py`
- [ ] Add menu handler `_view_labels(state)`:
  - Require experiment selected
  - Prompt for region (show list from `store.get_regions()`)
  - Prompt for condition if multiple
  - Launch napari
  - Report save result after napari closes

**Tests** (`test_view.py`):
- [ ] `percell3 view --help` shows options
- [ ] Missing experiment errors gracefully
- [ ] Missing napari shows install instructions
- [ ] View command with mock napari (patch `napari.Viewer`)

---

### Phase 4: pyproject.toml + Documentation

**Files**: `pyproject.toml`, `docs/03-segment/CLAUDE.md`

- [ ] Add napari optional dependency group:
  ```toml
  [project.optional-dependencies]
  napari = [
      "napari[all]>=0.5,<1.0",
      "napari-ome-zarr>=0.6",
  ]
  all = [
      "percell3[lif,czi,workflow,napari]",
  ]
  ```
- [ ] Add `gui` pytest marker for napari tests:
  ```toml
  [tool.pytest.ini_options]
  markers = [
      "slow: ...",
      "gui: marks tests requiring napari/display (deselect with '-m \"not gui\"')",
  ]
  ```
- [ ] Update segment module `__init__.py` to optionally re-export viewer API
- [ ] Document cellpose-napari as separate install in CLI help text

---

### Phase 5: Polish + Stretch Goals (Optional)

These are nice-to-haves, not required for initial release:

- [ ] **Region switcher widget**: napari dock widget with dropdown to switch
  regions without closing viewer. Saves current region's edits before switching.
- [ ] **Read-only mode**: `--read-only` flag that disables label editing
- [ ] **Channel colormap config**: User-configurable colormaps via experiment
  metadata or CLI flags
- [ ] **Unsaved changes warning**: Hook into napari close event to warn if
  labels modified but not explicitly reviewed
- [ ] **cellpose-napari detection**: Check if plugin installed, show hint in
  viewer status bar

---

## Dependency Graph

```
Phase 1 (Launcher)  ──────────▶ Phase 2 (Save-back) ──▶ Phase 3 (CLI)
                                                              │
                                                     Phase 4 (pyproject)
```

Phases 1-2 are the core viewer module. Phase 3 wires it to CLI.
Phase 4 is configuration. Phase 5 is optional polish.

## Edge Cases

| Scenario | Handling |
|----------|----------|
| napari not installed | `ImportError` with install instructions |
| No segmentation exists for region | Launch with channels only, no label layer |
| No channels in experiment | Error: "No channels found. Import images first." |
| Region doesn't exist | `ValueError` before launching napari |
| Labels unchanged after edit session | Skip save, print "No changes detected" |
| All labels erased (0 cells) | Save empty labels, create run with 0 cells, warn |
| Headless environment (no DISPLAY) | `RuntimeError` with helpful message |
| ExperimentStore locked by other process | SQLite WAL handles concurrent reads; write fails with clear error |
| napari crashes mid-edit | Edits lost (napari limitation). Document this. |
| Very large image (>4K px) | napari handles tiling internally; use dask arrays |
| Multiple segmentation runs exist | Load most recent run's labels |

## Acceptance Criteria

### Functional
- [ ] `percell3 view -e exp -r region1` launches napari with channel images + labels
- [ ] User can edit labels in napari (paint, erase, fill)
- [ ] Edited labels saved back to ExperimentStore on viewer close
- [ ] New segmentation run created with `model_name="napari_edit"`
- [ ] Cell properties re-extracted from edited labels
- [ ] Works without segmentation (channels only, no label layer)
- [ ] Graceful error when napari not installed

### Non-Functional
- [ ] napari import is lazy (not at module level)
- [ ] No napari dependency in core requirements
- [ ] All public functions have type hints and Google-style docstrings
- [ ] Tests pass without napari (gui-marked tests skipped)
- [ ] Tests pass with napari in headless mode (`QT_QPA_PLATFORM=offscreen`)

### Quality Gates
- [ ] All existing 511 tests still pass
- [ ] New tests: ~15-20 covering launcher, save-back, CLI
- [ ] No forbidden dependencies in viewer code (no click, no rich)
- [ ] Only ExperimentStore public API used (no `store._conn`)

## Institutional Learnings to Apply

1. **ExperimentStore public API only** — Never access `store._conn` or import
   from `percell3.core.queries`. Add public methods if needed.
   (From: `docs/solutions/architecture-decisions/segment-module-private-api-encapsulation-fix.md`)

2. **Lazy imports for optional deps** — Guard all napari imports inside
   functions. Use `_require_napari()` check at entry points.
   (From: `docs/solutions/architecture-decisions/cli-module-code-review-findings.md`)

3. **Version-aware adapters** — Pin napari to `>=0.5,<1.0`. Use `getattr()`
   fallback for any API that may change. Document tested versions.
   (From: `docs/solutions/integration-issues/cellpose-4-0-api-breaking-change.md`)

4. **Validate before writes** — Check region exists, experiment is open, labels
   are valid BEFORE creating segmentation run or writing to zarr.
   (From: todo-043 fix — ROI import writes-before-validation)

## Files Summary

| File | Action | Phase |
|------|--------|-------|
| `src/percell3/segment/viewer/__init__.py` | CREATE — public API + availability check | 1 |
| `src/percell3/segment/viewer/launcher.py` | CREATE — NapariLauncher | 1 |
| `src/percell3/segment/viewer/callbacks.py` | CREATE — label save-back | 2 |
| `src/percell3/segment/__init__.py` | MODIFY — re-export viewer API | 1 |
| `src/percell3/cli/view.py` | CREATE — Click command | 3 |
| `src/percell3/cli/main.py` | MODIFY — register view command | 3 |
| `src/percell3/cli/menu.py` | MODIFY — add viewer menu item | 3 |
| `pyproject.toml` | MODIFY — add napari optional dep | 4 |
| `tests/test_segment/test_viewer/__init__.py` | CREATE | 1 |
| `tests/test_segment/test_viewer/conftest.py` | CREATE — napari fixtures | 1 |
| `tests/test_segment/test_viewer/test_launcher.py` | CREATE | 1 |
| `tests/test_segment/test_viewer/test_callbacks.py` | CREATE | 2 |
| `tests/test_cli/test_view.py` | CREATE | 3 |

## References

### Internal
- Brainstorm: `docs/brainstorms/2026-02-13-cellpose-segmentation-workflow-brainstorm.md`
- Module 3a plan: `docs/plans/2026-02-13-feat-segmentation-module-cellpose-plan.md`
- Previous work phase: `docs/plans/2026-02-16-feat-next-work-phase-segment-merge-and-measure-plan.md`
- ExperimentStore API: `src/percell3/core/experiment_store.py`
- Label processor: `src/percell3/segment/label_processor.py`
- ROI importer: `src/percell3/segment/roi_import.py`
- CLI menu: `src/percell3/cli/menu.py`
- Encapsulation fix: `docs/solutions/architecture-decisions/segment-module-private-api-encapsulation-fix.md`
- Cellpose 4.0 fix: `docs/solutions/integration-issues/cellpose-4-0-api-breaking-change.md`

### External
- napari 0.7.0 docs: https://napari.org/dev/
- napari Labels API: https://napari.org/api/napari.layers.Labels.html
- napari event loop: https://napari.org/dev/guides/event_loop.html
- napari testing: https://napari.org/dev/developers/contributing/testing.html
- cellpose-napari plugin: https://github.com/MouseLand/cellpose-napari
- napari-ome-zarr: https://github.com/ome/napari-ome-zarr
