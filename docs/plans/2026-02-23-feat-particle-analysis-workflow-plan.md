---
title: "feat: Particle Analysis Workflow"
type: feat
date: 2026-02-23
---

# Particle Analysis Workflow

## Overview

Add a "Particle Analysis Workflow" to PerCell 3 that chains the full analysis
pipeline: FOV selection, Cellpose segmentation, measurement, Otsu thresholding
with napari visual QC, particle analysis, and Prism CSV export. All manual
configuration is collected upfront except thresholding, which requires
interactive napari review per FOV per group.

## Problem Statement / Motivation

Currently, running a full particle analysis requires manually navigating 4-5
separate menu items in sequence (Segment → Measure → Threshold → Export),
re-entering overlapping configuration (channel names, FOV selection) at each
step, and remembering the correct order. This is error-prone and tedious for
experiments with many FOVs. A workflow bundles these steps into a single
guided flow.

## Proposed Solution

A new `_particle_workflow()` handler in `menu.py` that:

1. **Upfront configuration** — collects all parameters in one go
2. **Automated stages** — runs segmentation and measurement without interaction
3. **Interactive threshold** — launches napari QC per FOV/group (reuses existing `_apply_threshold` logic)
4. **Automated export** — writes Prism CSVs to a user-specified directory

This is implemented as a **menu-driven orchestrator function**, NOT as a
`WorkflowDAG` step. The existing workflow engine assumes fully automated steps
and has no mechanism for interactive napari gates mid-pipeline. A menu handler
avoids that complexity while reusing all existing domain logic.

## User Flow

### Step 1: Upfront Configuration (Interactive)

```
PerCell 3 — Particle Analysis Workflow

Step 1: Select FOVs
┌──────┬─────────┬────────────┬─────────┬─────────────┬───────┬───────┐
│ #    │ FOV     │ Condition  │ Bio Rep │ Shape       │ Cells │ Model │
├──────┼─────────┼────────────┼─────────┼─────────────┼───────┼───────┤
│ 1    │ FOV_001 │ control    │ 1       │ 3256 x 3246 │     0 │       │
│ 2    │ FOV_001 │ treated    │ 1       │ 3253 x 3254 │     0 │       │
└──────┴─────────┴────────────┴─────────┴─────────────┴───────┴───────┘
Select FOVs (numbers, 'all', or blank=all): all

Step 2: Segmentation
  Channel to segment:
    [1] DAPI
    [2] GFP
    [3] RFP
  Segmentation channel: 1
  Model: cpsam (default)
  Cell diameter in pixels (blank = auto-detect):

Step 3: Threshold Channels
  Channels to threshold (select multiple):
    [1] DAPI
    [2] GFP
    [3] RFP
  Threshold channels: 2,3

Step 4: Grouping
  Channel for grouping metric:
    [1] DAPI
    [2] GFP
    [3] RFP
  Grouping channel: 2
  Metric for grouping:
    [1] mean_intensity
    [2] median_intensity
    [3] integrated_intensity
    [4] area_um2
  Grouping metric: 1

Step 5: Export
  Output directory: ~/prism_results

Workflow settings:
  FOVs:           8 selected
  Segmentation:   DAPI / cpsam / auto-detect
  Threshold:      GFP, RFP (Otsu)
  Grouping:       GFP / mean_intensity
  Measurement:    all channels
  Export:         ~/prism_results (Prism format)
  [1] Yes
  [2] No
Proceed?
```

### Step 2: Segmentation (Automated)

- Runs `SegmentationEngine.run()` with selected channel, model=cpsam, selected FOVs
- Shows progress bar per FOV
- If a FOV fails segmentation, logs warning and continues with remaining FOVs
- After segmentation completes, auto-measures all channels on all FOVs (same as current `_segment_cells` behavior)

### Step 3: Measurement (Automated)

- Already handled by the auto-measure in step 2
- No additional action needed

### Step 4: Thresholding (Interactive per FOV)

For each selected FOV, for each threshold channel:
1. Run `CellGrouper.group_cells()` to GMM-group cells
2. For each group: launch napari viewer with `launch_threshold_viewer()`
3. User accepts/skips/adjusts threshold per group
4. Run `ThresholdEngine.threshold_group()` to store threshold result
5. Run `ParticleAnalyzer.analyze_fov()` to detect and measure particles
6. Store particles, summary measurements, and particle label images

This reuses the exact logic from the existing `_apply_threshold()` handler
(lines 1154-1397 of `menu.py`), extracted into a reusable function.

### Step 5: Export (Automated)

- Calls `store.export_prism_csv()` with all channels, all metrics, scope=whole_cell
- Creates output directory if it doesn't exist
- Prints summary of files written

## Technical Approach

### Architecture

The workflow is a single function `_particle_workflow(state)` in `menu.py` that:

1. Collects all config into a `dict` or dataclass
2. Calls existing engine/analyzer APIs directly
3. Reuses `_apply_threshold_for_fov()` (extracted helper) for the interactive step

**No changes to the workflow engine.** The DAG-based engine is designed for
fully automated pipelines. The interactive napari gate doesn't fit that model.
The menu handler approach is simpler and uses all the same domain logic.

### Implementation Phases

#### Phase 1: Extract threshold logic into reusable helper

Extract the per-FOV threshold loop body from `_apply_threshold()` (lines 1232-1391)
into a standalone function:

```python
def _threshold_fov(
    store: ExperimentStore,
    fov_info: FovInfo,
    threshold_channel: str,
    grouping_channel: str,
    grouping_metric: str,
) -> tuple[int, int]:
    """Run grouping + threshold QC + particle analysis for one FOV.

    Returns:
        (fovs_processed, total_particles) — 1 or 0 for fovs_processed.
    """
```

This function contains the grouper → napari viewer → threshold_group →
particle analyzer chain. Both `_apply_threshold()` and the new workflow
handler call this shared function.

- [x] Extract `_threshold_fov()` from `_apply_threshold()` body
- [x] Refactor `_apply_threshold()` to call `_threshold_fov()` in its FOV loop
- [x] Verify existing threshold tests still pass

#### Phase 2: Build the workflow handler

Create `_particle_workflow(state)` in `menu.py`:

- [x] Implement upfront config collection (FOVs, seg channel, threshold channels, grouping, export dir)
- [x] Add confirmation summary before starting
- [x] Run segmentation via `SegmentationEngine.run()`
- [x] Auto-measure all channels via `Measurer.measure_fov()` per FOV
- [x] Loop over threshold channels × FOVs calling `_threshold_fov()`
- [x] Run Prism export via `store.export_prism_csv()`
- [x] Print final summary with counts

#### Phase 3: Wire into menu

- [x] Replace the stub in `_run_workflow()` (or the workflows menu item) with `_particle_workflow`
- [x] Update help text to describe the workflow

#### Phase 4: Error handling and edge cases

- [x] Handle segmentation failure on individual FOVs (skip, log, continue)
- [x] Handle "no measurements" for grouping metric (already handled by existing code — prints skip message)
- [x] Handle napari import failure (fallback to auto-accept, same as existing)
- [x] Handle empty experiment (no channels, no FOVs) — early exit with message
- [x] Allow user to cancel mid-workflow with `h` key (raises `_MenuHome`)
- [x] Handle case where FOVs already have cells (re-segmentation warning)

#### Phase 5: Tests

- [x] Test workflow config collection with mocked input
- [x] Test `_threshold_fov()` extracted function
- [x] Test workflow skips FOV on segmentation error
- [x] Test workflow produces Prism output directory

## Files to Modify/Create

| File | Action | Description |
|------|--------|-------------|
| `src/percell3/cli/menu.py` | Modify | Extract `_threshold_fov()`, add `_particle_workflow()`, wire into menu |
| `tests/test_cli/test_menu.py` | Modify | Add workflow integration tests |

## Edge Cases and Error Recovery

| Scenario | Behavior |
|----------|----------|
| Segmentation fails on 1 of N FOVs | Log warning, continue with remaining FOVs. Skip failed FOV in threshold step. |
| No measurements for grouping metric | Skip that FOV with message (existing `CellGrouper` raises `ValueError`). |
| napari not installed / no display | Fallback to auto-accept Otsu threshold (existing behavior in `_apply_threshold`). |
| User closes napari without clicking button | Treat as "Skip" for that group (existing behavior). |
| User clicks "Skip Remaining" in napari | Skip remaining groups for that FOV, move to next FOV. |
| Export directory already exists | Warn and require confirmation (or `--overwrite` equivalent in the prompt). |
| No threshold channels selected that have measurements | Particle analysis produces zero particles — export still runs with available data. |
| All FOVs skipped during threshold | Export still runs — will export segmentation + measurement data without particle metrics. |

## What This Does NOT Do

- **Does not modify the WorkflowDAG engine.** The engine stays as-is for future fully-automated workflows.
- **Does not add new WorkflowStep subclasses.** The interactive napari gate doesn't fit the step abstraction.
- **Does not fix API mismatches in `defaults.py`.** Those steps (`Measure`, `Threshold`) reference non-existent APIs — fixing them is a separate task.
- **Does not add masked measurement.** The workflow measures whole-cell only. Masked measurement can be run separately after thresholding.

## Acceptance Criteria

- [ ] `percell3` interactive menu → Workflows item launches the particle analysis workflow
- [ ] Upfront config collects: FOVs, seg channel, threshold channels, grouping channel/metric, export directory
- [ ] Segmentation runs with progress bar and handles per-FOV failures gracefully
- [ ] Auto-measurement runs on all channels after segmentation
- [ ] Threshold step launches napari per FOV per group per threshold channel
- [ ] Particle analysis runs automatically after threshold acceptance
- [ ] Prism CSV export produces output directory with per-metric files
- [ ] Existing `_apply_threshold` behavior unchanged (uses shared `_threshold_fov()`)
- [ ] All existing tests pass

## References

- `src/percell3/cli/menu.py:759` — `_segment_cells()` handler
- `src/percell3/cli/menu.py:949` — `_measure_channels()` handler
- `src/percell3/cli/menu.py:1154` — `_apply_threshold()` handler (to extract from)
- `src/percell3/segment/_engine.py` — `SegmentationEngine.run()` API
- `src/percell3/measure/measurer.py` — `Measurer.measure_fov()` API
- `src/percell3/measure/cell_grouper.py` — `CellGrouper.group_cells()` API
- `src/percell3/measure/thresholding.py` — `ThresholdEngine.threshold_group()` API
- `src/percell3/measure/threshold_viewer.py` — `launch_threshold_viewer()` API
- `src/percell3/measure/particle_analyzer.py` — `ParticleAnalyzer.analyze_fov()` API
- `src/percell3/core/experiment_store.py` — `export_prism_csv()` API
- `docs/plans/2026-02-23-feat-prism-csv-export-plan.md` — Prism export feature (completed)
