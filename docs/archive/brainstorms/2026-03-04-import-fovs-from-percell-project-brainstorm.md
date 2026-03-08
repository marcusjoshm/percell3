---
title: "Import FOVs from another PerCell 3 project"
date: 2026-03-04
type: feat
status: brainstorm
---

# Import FOVs from Another PerCell 3 Project

## What We're Building

A feature to import selected FOVs from one percell3 project into another, carrying over all associated data: channel images, segmentation labels, threshold masks, cells, measurements, and particles.

### Workflow

```
IMPORT menu → "Import from PerCell project"
  Step 1: Enter/browse path to source .percell directory
  Step 2: Select FOVs from the source project's FOV list
  Step 3: Confirm import (show summary of what will be copied)
  Step 4: Execute import with progress feedback
```

### What Gets Imported Per FOV

1. **Channel images** — all channels from `images.zarr/fov_{id}/`
2. **Segmentation labels** — from `labels.zarr/seg_{id}/` for each configured segmentation
3. **Threshold masks** — from `masks.zarr/thresh_{id}/` (mask + particle labels)
4. **Cells** — all cell records for the FOV (remapped to new IDs)
5. **Measurements** — all measurements for those cells (remapped IDs)
6. **Particles** — all particle records for the FOV (remapped IDs)
7. **fov_config** — segmentation/threshold assignments (remapped IDs)

### ID Remapping

Source and destination projects have independent ID sequences. Every entity needs remapping:
- `fov_id` → new ID in destination
- `segmentation_id` → new ID (or reuse if same-dimensioned whole_field exists)
- `threshold_id` → new ID in destination
- `cell_id` → new ID in destination
- `channel_id` → matched by name (reuse existing, create if missing)
- `condition_id` → matched by name (reuse existing, create if missing)
- `bio_rep_id` → matched by name (reuse existing, create if missing)

## Why This Approach

- **Full data import** preserves prior analysis work — no need to re-segment, re-threshold, or re-measure
- **Name-based matching** for conditions/channels avoids duplicates when projects share the same experimental setup
- **Under IMPORT menu** is the natural location alongside existing import functionality

## Key Decisions

1. **Import scope**: Everything — channels, segmentations, thresholds, cells, measurements, particles
2. **Name conflicts**: Reuse matching names for conditions, channels, bio_reps
3. **Segmentation names**: Must be unique in destination; append suffix if name collision (e.g., `manual_seg` → `manual_seg_imported_1`)
4. **Threshold names**: Same uniqueness handling as segmentations
5. **FOV display_name conflicts**: If destination already has a FOV with the same name, skip or append suffix
6. **Menu location**: Under existing IMPORT menu

## Open Questions

None — requirements are clear.
