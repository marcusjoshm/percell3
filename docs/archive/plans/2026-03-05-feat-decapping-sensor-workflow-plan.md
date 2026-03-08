---
title: "feat: Decapping Sensor Workflow"
type: feat
date: 2026-03-05
---

# feat: Decapping Sensor Workflow

## Overview

Add a CLI menu workflow ("Workflows > Decapping sensor") that orchestrates an 11-step
pipeline for decapping sensor analysis. The workflow automates segmentation/threshold
assignment, FOV matching, condensed-phase cleanup, BG subtraction pairing, and filtered
CSV export between interactive thresholding and plugin steps.

## Problem Statement

The decapping sensor analysis requires 11 steps with complex FOV matching
between steps: grouped thresholding, two rounds of split-halo dilute-phase extraction,
background subtraction, cross-step threshold assignment, and filtered CSV export.
Users currently perform each step manually via the CLI menu, manually assigning
segmentations and thresholds between steps. This is error-prone and time-consuming.

## Proposed Solution

A single `_decapping_sensor_workflow(state)` function in `menu.py` that:
1. Collects all parameters upfront (6 prefixes, channels, grouping settings)
2. Executes steps in sequence, calling existing functions directly
3. Pauses for interactive thresholding at steps 1, 4, 7
4. Tracks FOV lineage via explicit Python dicts (not name parsing)
5. Auto-handles segmentation assignment, condensed-phase deletion, and threshold assignment

## Technical Approach

### Lineage Tracking Strategy

Instead of parsing FOV names to trace lineage, the workflow builds explicit mappings
as it creates derived FOVs. After each plugin step, new FOVs are identified by
diffing the FOV list (snapshot before vs after). Mappings stored as:

```python
# original_fov_id → step2_dilute_fov_id
step2_lineage: dict[int, int] = {}

# step2_fov_id → step5_dilute_fov_id
step5_lineage: dict[int, int] = {}

# original_fov_id → list of step8_bgsub_fov_ids
step8_lineage: dict[int, list[int]] = {}

# step1 thresholds: original_fov_id → list of threshold_ids
step1_thresholds: dict[int, list[int]] = {}

# step7 thresholds: step5_fov_id → list of threshold_ids
step7_thresholds: dict[int, list[int]] = {}
```

Derived FOVs are identified after each plugin run by looking up the expected
display name: `f"{prefix}_{source_fov.display_name}_dilute_phase"`.

### Architecture

```
_decapping_sensor_workflow(state: MenuState) -> None
├── 1. Prerequisites check (channels, FOVs, cellular segmentation)
├── 2. Upfront parameter collection
│   ├── FOV selection (filter to cellular-segmented FOVs only)
│   ├── Grouping channel + metric + threshold channel
│   ├── Gaussian sigma, min particle area
│   ├── Split-halo parameters (measurement_channel, particle_channel, etc.)
│   ├── BG subtraction channel
│   └── 6 naming prefixes (validated against max name length)
├── 3. Confirmation summary
│
├── STEP 1: _threshold_fov() per original FOV (interactive napari)
│   └── Records step1_thresholds[fov_id] = [thr_id, ...]
│
├── STEP 2: registry.run_plugin("split_halo_condensate_analysis", ...)
│   ├── Delete condensed_phase FOVs
│   └── Build step2_lineage[original_fov_id] = dilute_fov_id
│
├── STEP 3: Auto-assign original segmentation to step 2 FOVs
│   └── set_fov_config_entry + on_config_changed per FOV
│
├── STEP 4: _threshold_fov() per step 2 FOV (interactive napari)
│
├── STEP 5: registry.run_plugin("split_halo_condensate_analysis", ...)
│   ├── Delete condensed_phase FOVs
│   └── Build step5_lineage[step2_fov_id] = dilute_fov_id
│
├── STEP 6: Auto-assign original segmentation to step 5 FOVs
│   └── set_fov_config_entry + on_config_changed per FOV
│
├── STEP 7: _threshold_fov() per step 5 FOV (interactive napari)
│   └── Records step7_thresholds[step5_fov_id] = [thr_id, ...]
│
├── STEP 8: registry.run_plugin("threshold_bg_subtraction", ...)
│   ├── Auto-build pairings: histogram=step5_fov, apply=original_fov
│   └── Build step8_lineage[original_fov_id] = [bgsub_fov_id, ...]
│
├── STEP 9: Auto-assign original segmentation to step 8 FOVs
│   └── set_fov_config_entry + on_config_changed per FOV
│
├── STEP 10: Auto-assign thresholds to step 8 FOVs
│   ├── Each BG-sub FOV gets: matching step 7 threshold
│   └── + ALL step 1 thresholds for the corresponding original FOV
│
├── STEP 11: Export filtered measurements CSV
│   ├── Build measurement pivot for all BG-subtracted FOVs
│   ├── Drop rows where {bg_channel}_area_mask_inside == 0
│   └── Keep only cell_ids with exactly 2 remaining rows (1 P-body + 1 DP)
│
└── Summary printout
```

### Key Implementation Details

#### Collecting thresholds from interactive steps

After each `_threshold_fov()` call, the workflow queries thresholds to find the
ones just created. Since `_threshold_fov` calls `ThresholdEngine.threshold_group`
with a constructed `name`, the workflow can find them by prefix + FOV name:

```python
# After _threshold_fov for one FOV:
all_thrs = store.get_thresholds()
new_thrs = [t for t in all_thrs if t.name.startswith(f"{prefix}_{fov_info.display_name}_")]
step1_thresholds[fov_info.id] = [t.id for t in new_thrs]
```

#### Identifying derived FOVs after plugin runs

After each split-halo plugin run, find the dilute-phase FOVs by name:

```python
all_fovs = store.get_fovs()
fov_by_name = {f.display_name: f for f in all_fovs}
for orig_fov in original_fovs:
    dilute_name = f"{dp_prefix}_{orig_fov.display_name}_dilute_phase"
    if dilute_name in fov_by_name:
        step2_lineage[orig_fov.id] = fov_by_name[dilute_name].id
```

#### Deleting condensed-phase FOVs

```python
for orig_fov in original_fovs:
    condensed_name = f"{dp_prefix}_{orig_fov.display_name}_condensed_phase"
    if condensed_name in fov_by_name:
        store.delete_fov(fov_by_name[condensed_name].id)
```

#### Step 8 auto-pairing

Build pairings from lineage dicts:

```python
pairings = []
for orig_fov_id, step2_fov_id in step2_lineage.items():
    step5_fov_id = step5_lineage.get(step2_fov_id)
    if step5_fov_id is not None:
        pairings.append({
            "histogram_fov_id": step5_fov_id,  # step 5 FOV (has step 7 thresholds)
            "apply_fov_id": orig_fov_id,         # original FOV
        })
```

#### Step 10 threshold assignment

```python
for orig_fov_id, bgsub_fov_ids in step8_lineage.items():
    # Get the segmentation from step 9's assignment
    for bgsub_fov_id in bgsub_fov_ids:
        config = store.get_fov_config(bgsub_fov_id)
        if not config:
            continue
        seg_id = config[0].segmentation_id

        # Assign ALL step 1 thresholds for this original FOV
        for thr_id in step1_thresholds.get(orig_fov_id, []):
            store.set_fov_config_entry(
                bgsub_fov_id, seg_id,
                threshold_id=thr_id,
                scopes=["whole_cell", "mask_inside", "mask_outside"],
            )

        # Assign matching step 7 threshold
        # BG-sub FOVs are created per-threshold, so we need to match
        # which step 7 threshold corresponds to which BG-sub FOV
        bgsub_fov_info = store.get_fov_by_id(bgsub_fov_id)
        for step5_fov_id, thr_ids in step7_thresholds.items():
            for thr_id in thr_ids:
                thr_info = store.get_threshold(thr_id)
                # Check if this threshold name appears in the BG-sub FOV name
                if thr_info.name in bgsub_fov_info.display_name:
                    store.set_fov_config_entry(
                        bgsub_fov_id, seg_id,
                        threshold_id=thr_id,
                        scopes=["whole_cell", "mask_inside", "mask_outside"],
                    )
                    break

        on_config_changed(store, bgsub_fov_id)
```

### Segmentation Assignment Helper

Steps 3, 6, and 9 all perform the same operation: assign the original FOV's cellular
segmentation to a derived FOV. Extract as a helper:

```python
def _assign_original_seg_to_derived(
    store: ExperimentStore,
    original_fov_id: int,
    derived_fov_id: int,
) -> None:
    """Assign the cellular segmentation from original FOV to a derived FOV."""
    orig_config = store.get_fov_config(original_fov_id)
    cellular_entries = [e for e in orig_config if e.segmentation_id is not None]
    if not cellular_entries:
        return
    seg_id = cellular_entries[0].segmentation_id

    # Clear auto-created whole-field config on derived FOV
    derived_config = store.get_fov_config(derived_fov_id)
    for entry in derived_config:
        store.delete_fov_config_entry(entry.id)

    # Assign original segmentation
    store.set_fov_config_entry(derived_fov_id, seg_id)
    on_config_changed(store, derived_fov_id)
```

## Implementation Phases

### Phase 1: Workflow Function Skeleton

- [x] Add `MenuItem("2", "Decapping sensor", ...)` to `_workflows_menu()` in `menu.py`
- [x] Create `_decapping_sensor_workflow(state: MenuState)` function
- [x] Implement prerequisites check:
  - [x] Verify channels exist
  - [x] Verify FOVs exist with cellular segmentation
  - [x] Verify cells exist (segmentation has been run)
- [x] Implement upfront parameter collection:
  - [x] FOV selection (filter to FOVs with cellular segmentation only)
  - [x] Grouping channel selection
  - [x] Grouping metric selection (mean_intensity, median_intensity, etc.)
  - [x] Threshold channel selection
  - [x] Gaussian sigma prompt (optional, default None)
  - [x] Min particle area prompt (default 1)
  - [x] Split-halo: measurement_channel, particle_channel, exclusion_channel,
        ring_dilation_pixels, exclusion_dilation_pixels, normalization_channel
  - [x] BG subtraction channel
  - [x] 6 naming prefixes via `_prompt_prefix()`
- [x] Validate all channel names exist in experiment
- [x] Show confirmation summary before proceeding

### Phase 2: Steps 1-3 (First Thresholding + Split-Halo + Assign)

- [x] **Step 1**: Loop over original FOVs, call `_threshold_fov()` for each
  - [x] Resolve segmentation_id from `fov_config` for each FOV
  - [x] After each FOV, query thresholds by prefix to build `step1_thresholds` dict
- [x] **Step 2**: Call split-halo plugin on original FOVs
  - [x] Build parameters dict with step 2 prefix
  - [x] Get cell_ids for selected FOVs
  - [x] Call `registry.run_plugin("split_halo_condensate_analysis", ...)`
  - [x] Delete condensed-phase FOVs by expected name
  - [x] Build `step2_lineage` dict by looking up dilute-phase FOV names
- [x] **Step 3**: Auto-assign segmentation using `_assign_original_seg_to_derived()`
  - [x] For each original FOV, assign its segmentation to the step 2 dilute FOV

### Phase 3: Steps 4-6 (Second Thresholding + Split-Halo + Assign)

- [x] **Step 4**: Loop over step 2 FOVs, call `_threshold_fov()` for each
  - [x] Use step 2 FOV's config for segmentation_id
  - [x] Use step 4 prefix for naming
- [x] **Step 5**: Call split-halo plugin on step 2 FOVs
  - [x] Build parameters dict with step 5 prefix
  - [x] Get cell_ids for step 2 FOVs
  - [x] Call plugin, delete condensed FOVs, build `step5_lineage`
- [x] **Step 6**: Auto-assign segmentation
  - [x] For each original FOV, trace through step2 → step5 lineage
  - [x] Assign original segmentation to step 5 FOV

### Phase 4: Steps 7-10 (Third Thresholding + BG Sub + Final Assignment)

- [x] **Step 7**: Loop over step 5 FOVs, call `_threshold_fov()` for each
  - [x] Build `step7_thresholds` dict
- [x] **Step 8**: Call BG subtraction plugin
  - [x] Build pairings from lineage dicts (step5 FOV as histogram, original as apply)
  - [x] Call `registry.run_plugin("threshold_bg_subtraction", ...)`
  - [x] Build `step8_lineage` dict by looking up BG-sub FOV names
- [x] **Step 9**: Auto-assign original segmentation to BG-sub FOVs
- [x] **Step 10**: Auto-assign thresholds to BG-sub FOVs
  - [x] Each BG-sub FOV gets: ALL step 1 thresholds for its original FOV
  - [x] Each BG-sub FOV gets: its matching step 7 threshold (by name match in display_name)
  - [x] Call `on_config_changed()` for each BG-sub FOV

### Phase 5: Step 11 (Filtered CSV Export) + Summary + Tests

- [x] **Step 11**: Export filtered measurements CSV for BG-subtracted FOVs
  - [x] Build measurement pivot for all BG-subtracted FOVs
  - [x] Drop rows where `{bg_channel}_area_mask_inside == 0` (no signal in mask)
  - [x] Keep only cell_ids with exactly 2 remaining rows (1 P-body + 1 DP)
  - [x] Write provenance-annotated CSV to `exports/` directory
- [x] Print final summary (FOVs processed, thresholds created, assignments made)
- [x] Run existing test suite to verify no regressions

## Acceptance Criteria

### Functional Requirements

- [ ] Workflow accessible via "Workflows > Decapping sensor" in CLI menu
- [ ] All 6 prefixes collected upfront before any processing
- [ ] Channel names validated against experiment before starting
- [ ] Steps 1, 4, 7 pause for interactive napari thresholding
- [ ] Condensed-phase FOVs auto-deleted after steps 2 and 5
- [ ] Segmentation auto-assigned from original FOVs at steps 3, 6, 9
- [ ] Step 8 auto-pairs histogram and apply FOVs correctly
- [ ] Step 10 assigns ALL step 1 thresholds + matching step 7 threshold to each BG-sub FOV
- [ ] Step 11 exports filtered CSV: drops zero-area rows and keeps only paired cells
- [ ] Final summary shows what was created

### Non-Functional Requirements

- [ ] Lineage tracked via explicit dicts (not name parsing)
- [ ] Uses existing `_threshold_fov`, plugin `.run()`, and store methods
- [ ] No schema changes required
- [ ] Follows existing CLI patterns (rich console, step headers, confirmation prompts)

## Dependencies & Risks

| Risk | Mitigation |
|------|-----------|
| User cancels napari mid-workflow | `_threshold_fov` returns (0, 0); workflow warns but continues |
| Dimension mismatch on segmentation assignment | Validate all FOVs share dimensions in prerequisites |
| Name collision on re-run | Plugins have idempotent FOV reuse; thresholds get `_2` suffix |
| Step 7 threshold name not found in BG-sub FOV name | Fallback: match by `source_fov_id` on threshold |

## References

### Internal References

- Brainstorm: `docs/brainstorms/2026-03-05-decapping-sensor-workflow-brainstorm.md`
- Grouped thresholding: `src/percell3/cli/menu.py:_threshold_fov` (line ~2557)
- Split-halo plugin: `src/percell3/plugins/builtin/split_halo_condensate_analysis.py`
- BG subtraction plugin: `src/percell3/plugins/builtin/threshold_bg_subtraction.py`
- Segmentation assignment: `src/percell3/cli/menu.py:_assign_segmentation` (line ~1835)
- Threshold assignment: `src/percell3/cli/menu.py:_assign_threshold` (line ~1900)
- Auto-measurement: `src/percell3/measure/auto_measure.py:on_config_changed`
- Prefix helper: `src/percell3/cli/menu.py:_prompt_prefix` (line ~185)
- Workflows menu: `src/percell3/cli/menu.py:_workflows_menu`
