---
topic: Decapping Sensor Workflow Automation
date: 2026-03-05
status: decided
---

# Decapping Sensor Workflow Automation

## What We're Building

A CLI menu workflow ("Workflows > Decapping Sensor") that orchestrates an 11-step
pipeline for decapping sensor analysis. The workflow automates segmentation
assignment, FOV matching, threshold assignment, condensed-phase cleanup, and
filtered CSV export between interactive thresholding and plugin steps.

### The Pipeline

Starting from a fully segmented dataset (FOVs with cellular segmentation):

| Step | Action | Interactive? | Outputs |
|------|--------|-------------|---------|
| 1 | Grouped thresholding on original FOVs | Yes (napari) | Threshold groups per FOV |
| 2 | Split-halo condensate analysis | No | Dilute phase FOVs (condensed deleted) |
| 3 | Assign original segmentation to step 2 FOVs | Auto | Config matrix updated |
| 4 | Grouped thresholding on step 2 FOVs | Yes (napari) | Threshold groups per dilute FOV |
| 5 | Split-halo again on step 2 FOVs | No | 2nd-round dilute phase FOVs (condensed deleted) |
| 6 | Assign original segmentation to step 5 FOVs | Auto | Config matrix updated |
| 7 | Grouped thresholding on step 5 FOVs | Yes (napari) | Threshold groups per 2nd dilute FOV |
| 8 | BG subtraction (step 7 FOVs as histogram, originals as apply) | No | BG-subtracted FOVs |
| 9 | Assign original segmentation to step 8 FOVs | Auto | Config matrix updated |
| 10 | Assign thresholds to step 8 FOVs | Auto | Each BG-sub FOV gets step 7 threshold + ALL step 1 groups |
| 11 | Export filtered CSV | Auto | Drops rows where area_mask_inside == 0, keeps cells with exactly 2 threshold rows (1 P-body + 1 DP) |

### Step 10 Detail

Each BG-subtracted FOV receives:
- Its **matching** step 7 threshold (the one used to estimate its background)
- **ALL** step 1 threshold groups for the corresponding original FOV

Example: If original FOV `As_WT_1` had 2 groups in step 1 (g1, g2) and 3 groups
in step 7 (g1, g2, g3), then `bgsub_As_WT_1_g1` gets:
- Step 7 threshold `Step7_As_WT_1_g1`
- Step 1 thresholds `Step1_As_WT_1_g1` AND `Step1_As_WT_1_g2`

## Why This Approach

**Dedicated workflow function** over DAG engine because:
- Interactive napari thresholding steps aren't supported by the workflow engine
- Single cohesive flow is easier to debug and modify
- Name-based FOV matching is sufficient (no schema changes needed)
- YAGNI: only one workflow needs this pattern right now

## Key Decisions

1. **Entry point**: CLI menu item under "Workflows" submenu
2. **Interactivity**: Thresholding steps (1, 4, 7) remain interactive with napari
3. **Condensed phase FOVs**: Created by plugin then auto-deleted by workflow
4. **Parameter prompting**: All prefixes prompted upfront before any processing
5. **Prefix strategy**: Type each of the 6 prefixes individually (max control)
6. **Split-halo parameters**: Prompted once, reused for both steps 2 and 5
7. **Thresholding parameters**: Same grouping channel, metric, threshold channel for all 3 steps
8. **BG subtraction pairing**: Auto-paired by matching original FOV name in derived name
9. **BG subtraction channel**: Separate prompt — may differ from threshold channel
10. **FOV lineage tracking**: Name-based matching (parse original FOV name from derived name)
11. **Threshold matching in step 10**: Name-based — extract original FOV name from BG-sub FOV name, find step 1 thresholds by `source_fov_id`
12. **Resumability**: Always run from start (no step selection); idempotent re-runs overwrite
13. **Threshold auto-assign before split-halo**: Already handled by the thresholding flow

## Upfront Parameter Collection

The workflow prompts for everything before starting:

1. **FOV selection**: Which original FOVs to process
2. **Grouping channel + metric**: For all thresholding steps (e.g., GFP, mean_intensity)
3. **Threshold channel**: For all thresholding steps
4. **Gaussian sigma**: Optional smoothing for thresholding
5. **Min particle area**: For particle filtering
6. **Split-halo parameters**: measurement_channel, particle_channel, etc.
7. **BG subtraction channel**: Which channel to subtract background from (may differ from threshold channel)
8. **Naming prefixes** (6 total, each typed individually):
   - Step 1 threshold prefix (e.g., "Step1")
   - Step 2 split-halo prefix (e.g., "DP1")
   - Step 4 threshold prefix (e.g., "Step4")
   - Step 5 split-halo prefix (e.g., "DP2")
   - Step 7 threshold prefix (e.g., "Step7")
   - Step 8 BG subtraction prefix (e.g., "BGsub")

## Name-Based Matching Strategy

With consistent prefix naming, the workflow can trace lineage:

```
Original:   As_WT_1
Step 2:     DP1_As_WT_1_dilute_phase        (contains "As_WT_1")
Step 5:     DP2_DP1_As_WT_1_dilute_phase_dilute_phase  (contains original via nesting)
Step 8:     BGsub_As_WT_1_Step7_..._Halo    (contains "As_WT_1" as apply FOV)
```

For step 8, the BG subtraction plugin already uses the **apply FOV name** in the
derived name, so matching back to the original is straightforward.

For step 10 threshold matching:
- Step 7 thresholds have `source_fov_id` pointing to step 5 FOVs
- Step 1 thresholds have `source_fov_id` pointing to original FOVs
- Match via: BG-sub FOV name contains original FOV name → find step 1 thresholds
  where `source_fov_id` matches that original FOV

## Open Questions

(None — all resolved during brainstorming)
