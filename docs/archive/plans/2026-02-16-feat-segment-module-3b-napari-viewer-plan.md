---
title: "feat: Segment Module 3b — napari Viewer Integration"
type: feat
date: 2026-02-16
revised: 2026-02-16
module: segment
---

# Segment Module 3b — napari Viewer Integration

## Overview

Build the napari-based viewer/editor for PerCell 3 — the GUI counterpart to the
headless segmentation engine (Module 3a). This module launches napari pre-loaded
with experiment data from ExperimentStore, supports manual label editing, and
saves edits back as new segmentation runs.

napari is an **optional dependency** (`pip install percell3[napari]`). Core
functionality (headless segmentation, measurement, export) works without it.

## Problem Statement / Motivation

Module 3a provides headless segmentation via `percell3 segment`. But microscopy
users need to:

1. **Visualize** segmentation results overlaid on channel images
2. **Correct** segmentation errors — merge split cells, delete debris, paint
   missed cells
3. **Multi-channel overlay** — view DAPI + GFP + labels simultaneously
4. **Create labels from scratch** — paint cells manually for regions where
   automated segmentation didn't run or failed

Without a viewer, users must export TIFFs, open in Fiji/napari manually, edit,
export back, and re-import — a fragile multi-step workflow that PerCell 3 should
automate.

## Dependencies & Prerequisites

- **Module 3a (Segment Engine)**: Complete. Provides `SegmentationEngine`,
  `extract_cells()`, `RoiImporter`, `BaseSegmenter` ABC.
- **Module 4 (Measure)**: Complete. Measurements reference `segmentation_id` —
  new viewer edits create a new run, old measurements are preserved.
- **Module 1 (Core)**: Complete. ExperimentStore provides `read_image()`,
  `read_image_numpy()`, `read_labels()`, `write_labels()`, `add_cells()`,
  `add_segmentation_run()`, `get_regions()`, `get_channels()`,
  `get_segmentation_runs()`.
- **napari>=0.6.0**: Optional. Current stable: 0.7.0 (Jan 2026). Requires
  Python 3.10+ (already our minimum). Do NOT bundle Qt backend — users choose.
- **cellpose-napari**: User-managed. Compatibility with Cellpose 4.x is
  unverified. Alternative: `napari-serialcellpose` explicitly supports 4.x.

**Not needed**: `napari-ome-zarr`. We load images through ExperimentStore, not
directly from zarr. This avoids an unnecessary dependency and gives us control
over colormaps and contrast limits.

No dependency on IO, CLI, or Workflow modules in domain code. CLI integration is
in the CLI module.

## Technical Approach

### Architecture

```
src/percell3/segment/viewer/ (NEW — Module 3b)
    │
    ├── __init__.py      ← Public API: launch_viewer(), NAPARI_AVAILABLE
    └── _viewer.py       ← Internal: _load_layers(), _save_edited_labels()
    │
    │  uses ↓
    │
src/percell3/segment/ (Module 3a — existing)
    └── label_processor.py   ← extract_cells() for re-extraction
    │
    │  uses ↓
    │
src/percell3/core/ (Module 1 — existing)
    └── ExperimentStore      ← All reads/writes go through public API
```

Two files, not three. The viewer logic is simple enough that a single internal
module (`_viewer.py`) handles both layer loading and save-back. The `__init__.py`
provides the public API and the napari availability check.

### Key Design Decisions

1. **Save on close via `napari.run()` blocking pattern**: `napari.run()` blocks
   until the viewer window closes. After it returns, we compare the label layer
   data to the original. If changed, save automatically. No event hooks needed —
   napari has no public `viewer.closed` event, and the post-`run()` pattern is
   simpler and more reliable.

2. **Change detection**: `np.array_equal(original, edited)`. Pixel-perfect
   comparison. If labels are unchanged, no save occurs, no segmentation run
   created. A single accidental brush stroke _will_ trigger a save — this is
   intentional (matches behavior of any editor with auto-save).

3. **One region per session**: Load one region at a time. User specifies
   `--region` on CLI. Multi-region is a future enhancement.

4. **All channels loaded**: All experiment channels loaded as separate napari
   image layers with `blending='additive'`. Labels loaded as label layer on top.
   Colormaps derived from `ChannelConfig.color` when available.

5. **Re-extract all cells**: When saving edited labels, re-extract properties
   for all cells in the region using `extract_cells()`. Simpler than diffing
   individual cells, consistent with headless segmentation behavior.

6. **New segmentation run with provenance**: Saved edits create a new
   `segmentation_run` with `model_name="napari_edit"` and parameters:
   ```python
   {
       "method": "napari_manual_edit",
       "parent_run_id": <id of displayed run, or null>,
       "channel": <channel used for segmentation display>,
   }
   ```
   Old runs and their cells/measurements are preserved (immutable history).

7. **Segmentation run selection**: When multiple runs exist, load the one with
   the **highest `id`** (most recent). No ambiguity. Future: add
   `--segmentation-run` CLI flag for explicit selection.

8. **Measurements preserved**: Editing labels creates a new segmentation run.
   Old cells and their measurements remain in the database, associated with the
   old `segmentation_id`. No data is deleted.

9. **Labels dtype**: ExperimentStore stores labels as int32. napari Labels layer
   works with integer arrays. We pass int32 directly — napari handles it.

10. **cellpose-napari is user-managed**: PerCell 3 doesn't bundle or configure
    the plugin. If user runs Cellpose from within napari, we pick up whatever is
    in the label layer on close.

11. **ExperimentStore public API only**: No `store._conn`, no `queries` import.
    (From: todo-034 fix)

12. **Contrast limits explicit for lazy arrays**: Set `contrast_limits` when
    adding image layers to avoid expensive auto-computation on dask arrays.
    Default: `[0, dtype_max]` (65535 for uint16, 255 for uint8).

### File Structure

```
src/percell3/segment/
├── viewer/                      # NEW: napari integration subpackage
│   ├── __init__.py              # Public API: launch_viewer, NAPARI_AVAILABLE
│   └── _viewer.py               # Internal: layer loading + save-back
├── __init__.py                  # MODIFY: re-export viewer API via __getattr__
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
├── test_viewer.py               # NEW: viewer tests (single file, not subpackage)
└── (existing test files)

tests/test_cli/
└── test_view.py                 # NEW: CLI view command tests
```

## Implementation Phases

### Phase 1: Viewer Core — Launch + Save-back

**Files**: `viewer/__init__.py`, `viewer/_viewer.py`

- [x] Create `viewer/__init__.py` with lazy napari check:
  ```python
  def _napari_available() -> bool:
      """Check if napari is importable without importing it at module level."""
      try:
          import napari  # noqa: F401
          return True
      except ImportError:
          return False

  NAPARI_AVAILABLE: bool = _napari_available()

  def launch_viewer(
      store: "ExperimentStore",
      region: str,
      condition: str,
      channels: list[str] | None = None,
  ) -> int | None:
      """Launch napari viewer. Returns run_id if labels were edited, None otherwise."""
      if not NAPARI_AVAILABLE:
          raise ImportError(
              "napari is required for the viewer. "
              "Install with: pip install 'percell3[napari]'"
          )
      from percell3.segment.viewer._viewer import _launch
      return _launch(store, region, condition, channels)
  ```

- [x] Create `viewer/_viewer.py` with internal implementation:

  **`_launch()` function**:
  1. Validate region exists via `store.get_regions(condition=condition)`
  2. Validate at least one channel exists via `store.get_channels()`
  3. Detect headless environment (no DISPLAY on non-macOS)
  4. Create `napari.Viewer(title="PerCell 3 — {region} ({condition})")`
  5. Load channel images as layers
  6. Load latest labels if segmentation exists
  7. Snapshot original labels: `original = labels.copy()` or `None`
  8. Call `napari.run()` — blocks until close
  9. Compare labels. If changed, call `_save_edited_labels()`
  10. Return `run_id` or `None`

  **`_load_channel_layers()` helper**:
  - For each channel: `store.read_image(region, condition, channel)` → dask array
  - `viewer.add_image(data, name=ch.name, colormap=_channel_colormap(ch), blending='additive', contrast_limits=_default_limits(data.dtype))`
  - Colormap mapping: parse `ChannelConfig.color` hex → napari colormap name
    - `"0000FF"` / blue → `"blue"`, `"00FF00"` / green → `"green"`,
      `"FF0000"` / red → `"red"`, fallback → `"gray"`

  **`_load_label_layer()` helper**:
  - Get segmentation runs via `store.get_segmentation_runs()`
  - Filter to runs for this channel/region. Pick highest `id`.
  - `store.read_labels(region, condition)` → int32 ndarray
  - `viewer.add_labels(data, name="segmentation", opacity=0.5)`
  - If no runs exist, add empty labels layer for painting from scratch:
    `np.zeros(image_shape, dtype=np.int32)`
  - Return `(original_labels_copy, parent_run_id)`

  **`_save_edited_labels()` function**:
  ```python
  def _save_edited_labels(
      store: ExperimentStore,
      region: str,
      condition: str,
      edited_labels: np.ndarray,
      parent_run_id: int | None,
      channel: str,
  ) -> int:
      """Save edited labels. Returns new run_id."""
      # 1. Validate: labels are 2D integer, values >= 0
      # 2. Convert to int32 via np.asarray(labels, dtype=np.int32)
      # 3. Create segmentation run
      # 4. Write labels to zarr
      # 5. Extract cells via extract_cells()
      # 6. Insert cells to DB
      # 7. Update run cell count
      # 8. Return run_id
  ```
  - Parameters JSON: `{"method": "napari_manual_edit", "parent_run_id": ..., "channel": ...}`
  - On extraction failure after zarr write: log error, set cell_count=0 on run.
    Labels are preserved; user can re-extract later.

- [x] Headless detection:
  ```python
  import os, sys
  if sys.platform != "darwin" and not os.environ.get("DISPLAY"):
      raise RuntimeError(
          "napari requires a display. Set DISPLAY or use X11 forwarding."
      )
  ```

**Tests** (`test_viewer.py`):

All tests guarded with `pytest.importorskip("napari")` and marked `@pytest.mark.gui`.

- [x] `NAPARI_AVAILABLE` is True when napari installed
- [x] `launch_viewer()` raises `ImportError` when napari missing (mock the flag)
- [x] `_load_channel_layers()` adds correct number of image layers
- [x] `_load_label_layer()` loads labels when segmentation exists
- [x] `_load_label_layer()` creates empty labels when no segmentation exists
- [x] Default colormaps applied from ChannelConfig.color
- [x] `_save_edited_labels()` — modified labels save and return run_id
- [x] `_save_edited_labels()` — round-trip: zarr read matches saved labels
- [x] `_save_edited_labels()` — cell count in DB matches unique labels
- [x] `_save_edited_labels()` — cell properties (area, centroid) correct
- [x] `_save_edited_labels()` — empty labels (all erased) create run with 0 cells
- [x] Change detection: `np.array_equal` returns True for identical arrays
- [x] Contrast limits set explicitly (no auto-compute on lazy arrays)

Note: Tests use `make_napari_viewer(show=False)` fixture. Run with
`QT_QPA_PLATFORM=offscreen`.

---

### Phase 2: CLI + Menu Integration

**Files**: `cli/view.py`, `cli/main.py`, `cli/menu.py`

- [x] Create `percell3 view` Click command:
  ```python
  @click.command()
  @click.option("-e", "--experiment", required=True, type=click.Path(exists=True))
  @click.option("-r", "--region", required=True, help="Region name to view.")
  @click.option("--condition", default=None, help="Condition (auto-detected if only one).")
  @click.option("--channels", default=None, help="Comma-separated channels to load.")
  @error_handler
  def view(experiment, region, condition, channels):
      """Launch napari to view and edit segmentation labels."""
  ```
- [x] Handle `--condition` default: if experiment has one condition, use it
  automatically. If multiple, require `--condition` or error with list.
- [x] Register in `main.py`: `cli.add_command(view)`
- [x] Add "View in napari" to interactive menu in `menu.py`:
  - Require experiment selected
  - Prompt for region (show list from `store.get_regions()`)
  - Prompt for condition if multiple
  - Launch viewer
  - Report save result after napari closes ("Saved N cells" or "No changes")

**Tests** (`test_view.py`):
- [x] `percell3 view --help` shows options
- [x] Missing experiment errors gracefully
- [x] Missing napari shows install instructions (mock import)
- [x] View command with mock napari (patch `napari.Viewer` + `napari.run`)
- [x] Auto-detect condition when only one exists

---

### Phase 3: pyproject.toml + Wiring

**Files**: `pyproject.toml`, `segment/__init__.py`

- [x] Add napari optional dependency group:
  ```toml
  [project.optional-dependencies]
  napari = [
      "napari>=0.6.0",
  ]
  all = [
      "percell3[lif,czi,workflow,napari]",
  ]
  ```
  Do NOT include `napari[all]` — let users choose their Qt backend separately.
  Do NOT include `napari-ome-zarr` — we load via ExperimentStore.

- [x] Add `gui` pytest marker:
  ```toml
  [tool.pytest.ini_options]
  markers = [
      "slow: marks tests as slow (requires cellpose model download, deselect with '-m \"not slow\"')",
      "gui: marks tests requiring napari (deselect with '-m \"not gui\"')",
  ]
  ```

- [x] Update `segment/__init__.py` to re-export viewer via `__getattr__`:
  ```python
  # Add to existing __getattr__
  if name in ("launch_viewer", "NAPARI_AVAILABLE"):
      from percell3.segment.viewer import launch_viewer, NAPARI_AVAILABLE
      return {"launch_viewer": launch_viewer, "NAPARI_AVAILABLE": NAPARI_AVAILABLE}[name]
  ```

---

## Edge Cases

| Scenario | Handling |
|----------|----------|
| napari not installed | `ImportError` with install instructions |
| Headless (no DISPLAY) | `RuntimeError` with message, skip on macOS (always has display) |
| No segmentation exists | Launch with channels + empty labels layer for painting |
| No channels in experiment | Error: "No channels found. Import images first." |
| Region doesn't exist | `ValueError` before launching napari |
| Labels unchanged | Skip save, print "No changes detected" |
| All labels erased (0 cells) | Save empty labels, create run with 0 cells, warn |
| Multiple segmentation runs | Load most recent (highest id) |
| Labels from scratch (no prior run) | parent_run_id=None in parameters |
| napari crashes mid-edit | Edits lost. Document limitation. |
| Large images (>4K px) | Load as dask arrays; napari handles tiling |
| Cell extraction fails after save | Labels persisted, run has cell_count=0. Log error. |
| Negative label values | Reject: validate labels >= 0 before save |
| Labels not 2D | Reject: validate ndim == 2 before save |
| Force-quit (Ctrl+C) | Edits lost. Same as crash. |

## Acceptance Criteria

### Functional
- [ ] `percell3 view -e exp -r region1` launches napari with channel images + labels
- [ ] User can edit labels in napari (paint, erase, fill)
- [ ] Edited labels saved back to ExperimentStore on viewer close
- [ ] New segmentation run created with `model_name="napari_edit"` and provenance metadata
- [ ] Cell properties re-extracted from edited labels
- [ ] Works without prior segmentation (empty labels layer, painting from scratch)
- [ ] Graceful error when napari not installed
- [ ] Most recent segmentation run loaded when multiple exist
- [ ] Old measurements preserved when new run created

### Non-Functional
- [ ] napari import is lazy (not at module level)
- [ ] No napari dependency in core requirements
- [ ] All public functions have type hints and Google-style docstrings
- [ ] Tests pass without napari (gui-marked tests skipped)
- [ ] Tests pass with napari in headless mode (`QT_QPA_PLATFORM=offscreen`)

### Quality Gates
- [ ] All existing tests still pass
- [ ] New tests: ~15 covering viewer, save-back, CLI
- [ ] No forbidden dependencies in viewer code (no click, no rich in domain code)
- [ ] Only ExperimentStore public API used (no `store._conn`)
- [ ] Contrast limits set explicitly for all image layers

## Institutional Learnings to Apply

1. **ExperimentStore public API only** — Never access `store._conn` or import
   from `percell3.core.queries`. Add public methods if needed.
   (From: `docs/solutions/architecture-decisions/segment-module-private-api-encapsulation-fix.md`)

2. **Lazy imports for optional deps** — Guard all napari imports inside
   functions or behind `_napari_available()`. Never import napari at module level.
   (From: existing `__getattr__` pattern in `segment/__init__.py`)

3. **Version-aware adapters** — Pin napari to `>=0.6.0`. The Viewer, add_image,
   and add_labels APIs are stable across 0.6-0.7. Document tested version.
   (From: `docs/solutions/integration-issues/cellpose-4-0-api-breaking-change.md`)

4. **Validate before writes** — Check region exists, experiment has channels,
   labels are valid BEFORE creating segmentation run or writing to zarr.
   (From: todo-043 fix — ROI import writes-before-validation)

5. **np.asarray for dtype** — Use `np.asarray(labels, dtype=np.int32)` for
   zero-copy when already int32.
   (From: todo-052 — redundant astype copies)

## Files Summary

| File | Action | Phase |
|------|--------|-------|
| `src/percell3/segment/viewer/__init__.py` | CREATE — public API + availability | 1 |
| `src/percell3/segment/viewer/_viewer.py` | CREATE — layer loading + save-back | 1 |
| `src/percell3/segment/__init__.py` | MODIFY — re-export via __getattr__ | 3 |
| `src/percell3/cli/view.py` | CREATE — Click command | 2 |
| `src/percell3/cli/main.py` | MODIFY — register view command | 2 |
| `src/percell3/cli/menu.py` | MODIFY — add viewer menu item | 2 |
| `pyproject.toml` | MODIFY — add napari optional dep + gui marker | 3 |
| `tests/test_segment/test_viewer.py` | CREATE — viewer + save-back tests | 1 |
| `tests/test_cli/test_view.py` | CREATE — CLI view command tests | 2 |

## References

### Internal
- Brainstorm: `docs/brainstorms/2026-02-13-cellpose-segmentation-workflow-brainstorm.md`
- Module 3a plan: `docs/plans/2026-02-13-feat-segmentation-module-cellpose-plan.md`
- ExperimentStore API: `src/percell3/core/experiment_store.py`
- Label processor: `src/percell3/segment/label_processor.py`
- Existing `__getattr__` pattern: `src/percell3/segment/__init__.py`
- CLI menu: `src/percell3/cli/menu.py`
- Encapsulation fix: `docs/solutions/architecture-decisions/segment-module-private-api-encapsulation-fix.md`
- Cellpose 4.0 fix: `docs/solutions/integration-issues/cellpose-4-0-api-breaking-change.md`

### External
- napari 0.7.0 release: https://github.com/napari/napari/releases/tag/v0.7.0
- napari Viewer API: https://napari.org/dev/api/napari.Viewer.html
- napari Labels layer: https://napari.org/stable/howtos/layers/labels.html
- napari testing: https://napari.org/dev/developers/contributing/testing.html
- cellpose-napari: https://github.com/MouseLand/cellpose-napari
- napari-serialcellpose (Cellpose 4.x): https://github.com/guiwitz/napari-serialcellpose
