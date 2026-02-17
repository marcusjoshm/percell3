---
title: "feat: Install napari, test viewer integration, and plan next modules"
type: feat
date: 2026-02-17
---

# Install Napari, Test Viewer Integration, and Plan Next Modules

## Overview

The napari viewer code is complete (19 unit tests, all 540 tests passing) on the `feat/napari-viewer` branch, but napari itself is not installed in the development environment. This plan covers installing napari, manually testing the viewer with real microscopy data, merging to main, and then sequencing the remaining work (measure CLI wiring + plugin system).

## Problem Statement / Motivation

The interactive menu has a "View in napari" option and the CLI has `percell3 view`, but both report "napari is not installed" because `NAPARI_AVAILABLE=False`. The viewer code has only been tested with mocks — it needs validation with a real napari window and real experiment data before merging to main.

After the viewer is validated, two gaps remain:
- **Measure CLI**: Domain engine (49 tests) works, but `percell3 measure` and `percell3 threshold` are stubs
- **Plugin system (Module 5)**: Completely unstarted — the only module with no implementation

## Current State

```
Module Status:
  1. Core .................. COMPLETE (126 tests, on main)
  2. IO .................... COMPLETE (109 tests, on main)
  3. Segment (headless) .... COMPLETE (98 tests, on main)
  3b. Segment (napari) ..... COMPLETE (19 tests, on feat/napari-viewer) <-- needs merge
  4. Measure (domain) ...... COMPLETE (49 tests, on main)
  4b. Measure (CLI) ........ STUB (cli/stubs.py) <-- needs wiring
  5. Plugins ............... NOT STARTED (skeleton only)
  6. Workflow .............. COMPLETE (78 tests, on main)
  7. CLI ................... MOSTLY COMPLETE (80 tests, on main)

  napari installed: NO
  NAPARI_AVAILABLE: False
  Total tests: 540 passing
```

## Proposed Solution

### Phase 1: Install Napari and Smoke Test (~30 min)

- [x] Install napari: `pip install -e '.[napari]'` — napari 0.6.6 installed
- [x] Verify: `python -c "import napari; print(napari.__version__)"` — 0.6.6
- [x] Verify: `python -c "from percell3.segment.viewer import NAPARI_AVAILABLE; print(NAPARI_AVAILABLE)"` — True
- [x] Run existing tests: `pytest tests/test_segment/test_viewer.py -v` — 19 passed
- [x] Smoke test: `percell3 view --help` shows options

### Phase 2: Create Test Experiment (~15 min)

If no `.percell` experiment exists with real data, create one:

- [ ] Create experiment: `percell3 create test_experiment.percell`
- [ ] Import TIFF images: `percell3 import -e test_experiment.percell -s <tiff_dir>`
- [ ] Run segmentation: `percell3 segment -e test_experiment.percell --channel DAPI --model cyto3`
- [ ] Verify data exists: `percell3 query -e test_experiment.percell channels` / `regions` / `cells`

### Phase 3: Interactive Viewer Testing (~1 hour)

Test each user flow in a real napari window:

#### Basic Viewing
- [ ] Launch from CLI: `percell3 view -e test_experiment.percell -r <region>`
- [ ] Launch from interactive menu: `percell3` → "View in napari"
- [ ] Verify all channels load as separate image layers with additive blending
- [ ] Verify colormaps match channel colors (DAPI=blue, GFP=green, etc.)
- [ ] Verify existing segmentation labels load with 50% opacity
- [ ] Verify viewer title shows region name and condition

#### Edit and Save
- [ ] Paint a new cell (label 3+) using napari's brush tool
- [ ] Close napari window
- [ ] Verify "Labels saved" message with new run_id
- [ ] Verify: `percell3 query -e test_experiment.percell cells` shows new cells
- [ ] Re-open viewer — verify new labels are loaded (not old ones)

#### No-Edit Path
- [ ] Open viewer, look at labels but don't edit
- [ ] Close napari window
- [ ] Verify "No changes detected" message (hash-based detection)

#### From-Scratch Path
- [ ] Open viewer on a region with NO existing segmentation
- [ ] Verify empty label layer appears
- [ ] Paint some cells
- [ ] Close — verify save creates new segmentation run

#### Channel Selection
- [ ] Launch with `--channels DAPI` — verify only DAPI loads
- [ ] Launch with `--channels DAPI,GFP` — verify both load

#### Error Handling
- [ ] Launch on non-existent region — verify helpful error message
- [ ] Launch on non-existent condition — verify helpful error message

### Phase 4: Fix Any Issues Found (~variable)

- [ ] Document any bugs or UX issues discovered during testing
- [ ] Fix issues and re-test
- [ ] Run full test suite: `pytest tests/ -v`

### Phase 5: Merge to Main (~15 min)

- [ ] Merge `feat/napari-viewer` into `main` (or create PR)
- [ ] Delete feature branch after merge
- [ ] Verify `main` has all 540+ tests passing

### Phase 6: Plan Next Module Work

After napari is validated and merged, the remaining work in priority order:

#### 6a. Wire Measure CLI (~2-3 hours)
The domain engine (Module 4) is complete with 49 tests. Only the CLI commands need wiring:
- Replace `percell3 measure` stub with real implementation
- Replace `percell3 threshold` stub with real implementation
- Add menu entries for measure/threshold
- Wire `BatchMeasurer` with Rich progress bar
- Files: `cli/measure.py`, `cli/threshold.py` (new), update `cli/stubs.py`, `cli/main.py`

#### 6b. Build Plugin System — Module 5 (~4-6 hours)
The only unstarted module. Spec exists at `docs/05-plugins/spec.md`:
- `plugins/base.py` — AnalysisPlugin ABC
- `plugins/registry.py` — PluginRegistry with entry_points discovery
- `plugins/builtin/intensity_grouping.py` — IntensityGroupingPlugin
- `plugins/builtin/colocalization.py` — ColocalizationPlugin
- `plugins/builtin/flim_phasor.py` — FlimPhasorPlugin scaffold
- CLI: `percell3 plugin list`, `percell3 plugin run`

## Technical Considerations

- **napari version**: Pinned to `>=0.6.0` in pyproject.toml. Test with whatever version pip resolves.
- **Qt backend**: napari requires PyQt5 or PyQt6. The install may pull in a Qt backend. If Qt conflicts arise, try `pip install pyqt5` explicitly.
- **macOS display**: No `DISPLAY` env var needed on macOS (Darwin check in code handles this).
- **Memory**: Hash-based change detection uses ~32 bytes instead of a full array copy. Safe for large images.
- **Headless CI**: Viewer tests use mocks. No napari needed in CI. The `gui` pytest marker exists for future napari-requiring tests.

## Dependencies & Risks

| Risk | Mitigation |
|------|-----------|
| napari install fails (Qt conflicts) | Try `pip install pyqt5` first, or use conda |
| napari API changed in newer version | Pinned `>=0.6.0`, test with installed version |
| Real data reveals bugs not caught by mocks | Phase 3 testing catches these before merge |
| Large image OOM | SHA-256 hash avoids array copy; napari handles lazy loading |

## Acceptance Criteria

- [ ] napari installed and `NAPARI_AVAILABLE=True`
- [ ] Viewer launches from both CLI and interactive menu
- [ ] Channels display with correct colormaps
- [ ] Label editing triggers save on close
- [ ] No-edit close triggers no save (hash detection works)
- [ ] From-scratch painting creates new segmentation run
- [ ] All 540+ tests still pass
- [ ] `feat/napari-viewer` merged to main
- [ ] Next phase (measure CLI or plugins) chosen and planned

## References

- Napari viewer implementation plan: `docs/plans/2026-02-16-feat-segment-module-3b-napari-viewer-plan.md`
- Viewer code review findings: `docs/solutions/architecture-decisions/viewer-module-code-review-findings.md`
- P3 cleanup findings: `docs/solutions/code-quality/viewer-module-p3-refactoring-and-cleanup.md`
- Module 4 measure spec: `docs/04-measure/spec.md`
- Module 5 plugins spec: `docs/05-plugins/spec.md`
- Previous roadmap plan: `docs/plans/2026-02-16-feat-next-work-phase-segment-merge-and-measure-plan.md`
