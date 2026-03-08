---
title: "Combined mask overwrites last group's threshold mask"
category: logic-errors
tags: [thresholding, particle-analysis, grouped-thresholding, mask, data-corruption]
module: cli/menu.py, measure/thresholding.py
symptom: "Last group in grouped thresholding has particles in ALL cells instead of only group cells; CSV export shows no zeros for last group"
root_cause: "Combined mask (union of all groups) was written to the last threshold ID, overwriting its group-restricted mask before particle analysis"
fix_commit: "82bb60c"
date: 2026-03-04
---

# Combined Mask Overwrites Last Group's Threshold Mask

## Problem

When running grouped intensity thresholding (e.g., g1 and g2 groups), the
last group's particle measurements were incorrect. All cells showed non-zero
particle counts instead of only cells belonging to that group.

**User symptom:** In CSV export, g1 had expected zeros for non-g1 cells, but g2
had positive particle values for ALL 11 cells. Between g1 and g2 (which partition
the cells), exactly 11 entries should be zero and 11 positive. Instead only g1's
non-group cells were zero.

## Root Cause

In `_threshold_fov()` (menu.py), after each group's threshold was created with
a correctly group-restricted mask via `threshold_group()`, the code accumulated
a combined mask and wrote it to the last threshold:

```python
# BUG: accumulated union of all group masks
combined_mask |= (group_written > 0)

# BUG: wrote combined mask to last threshold, overwriting its group-only mask
_, _, last_thr_id = accepted_groups[-1]
store.write_mask(combined_mask.astype(np.uint8), last_thr_id)
```

The particle analysis loop ran AFTER this overwrite, so:
- First group (g1): mask still correct (not overwritten) → correct particle data
- Last group (g2): mask now contains g1+g2 combined → ALL cells get particles

## Diagnosis Approach

1. **Queried particle_count measurements** from the database for both groups'
   threshold IDs on the source FOV. Found threshold 1 (g1) had one zero (the g2
   cell), but threshold 2 (g2) had NO zeros — identical values to g1 for all
   non-g2 cells.

2. **Checked group tags** on cells — confirmed g1 had 10 cells, g2 had 1 cell.

3. **Verified the mask was correctly created** — `threshold_group()` produces
   `mask = (group_image > threshold_value) & cell_mask` which correctly restricts
   to group cells only.

4. **Traced the overwrite** — found the combined mask write between threshold
   creation and particle analysis. The last threshold's mask was overwritten
   with the union of all groups.

## Fix

Removed the combined mask accumulation and write entirely (3 lines of init +
8 lines of accumulate/write). Each group's threshold retains its correct
group-restricted mask for particle analysis.

## Key Lessons

### 1. Don't mutate stored data between write and downstream read

The threshold mask was written correctly by `threshold_group()`, then silently
overwritten before the particle analyzer read it. Any "post-processing" step
that modifies stored data between creation and consumption is a latent bug.

**Pattern to avoid:**
```python
for item in items:
    create_and_store(item)     # writes correct data

post_process_last(items[-1])   # modifies stored data ← BUG

for item in items:
    consume(item)              # reads corrupted data for last item
```

### 2. The last-item-only corruption pattern is hard to spot

Because only the last group is affected, the bug is invisible when there's only
one group. It only manifests with 2+ groups, and only affects the last one.
Testing with a single group would never catch this.

### 3. Downstream consumers may have their own merging logic

The split halo condensate analysis plugin already does its own particle label
merging with proper renumbering. The "helpful" combined mask was redundant and
harmful. Before adding convenience aggregations, check if downstream code
already handles this.

### 4. Verify particle data with SQL, not just visual inspection

The bug was invisible in the napari viewer (mask looked correct at write time).
It was only caught by querying `particle_count` measurements per cell per
threshold in the database and noticing the pattern: identical values across
groups except for the expected cell.

## Affected Data

Any experiment that used grouped intensity thresholding with 2+ groups has
incorrect particle measurements and particle labels for the LAST group's
threshold. The fix only prevents future corruption — existing data must be
re-thresholded to correct.

## Related

- `threshold_group()` in `src/percell3/measure/thresholding.py` — correctly
  creates group-restricted masks
- `ParticleAnalyzer.analyze_fov()` in `src/percell3/measure/particle_analyzer.py`
  — reads mask from store, intersects with cell labels
- Split halo plugin `merged_particle_labels` logic — does its own merging of
  particle labels across thresholds (lines 282-309)
