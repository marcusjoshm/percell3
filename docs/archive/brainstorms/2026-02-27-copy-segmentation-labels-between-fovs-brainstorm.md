---
topic: Copy Segmentation Labels Between FOVs
date: 2026-02-27
status: decided
---

# Copy Segmentation Labels Between FOVs

## What We're Building

A feature that lets users copy a segmentation (label image + cell records) from one FOV to another. The primary use case is applying the original FOV's segmentation to derived FOVs (e.g., `bg_sub_FOV1`, `condensed_phase_FOV1`) that share the same geometry.

## Why This Feature

Derived FOVs created by plugins (BG subtraction, split-halo-condensate) have the same pixel dimensions and cell layout as the original. Users need to measure these derived images per-cell, which requires a segmentation layer. Currently there's no way to reuse an existing segmentation — users would have to re-segment from scratch or manually paint labels.

## Key Decisions

- **Use case:** Primarily for derived FOVs that share geometry with the original
- **Copy type:** Exact copy of the label array — same cell boundaries, same pixel values
- **Cell extraction:** Re-run cell extraction on the target FOV (new `segmentation_run` record, fresh cell IDs in the database, proper provenance)
- **Access point:** Napari viewer dock widget with source/target FOV dropdowns
- **Target selection:** Any FOV in the experiment (warn if dimensions don't match, but allow it)
- **Overwrite behavior:** Overwrite silently if target already has labels (matches re-segmentation pattern)
- **Architecture:** Standalone `copy_labels_to_fov()` function + widget wrapper (testable, reusable from plugins)

## User Flow

1. User opens a FOV in napari viewer
2. "Copy Labels" dock widget is visible on the right
3. Source FOV dropdown defaults to the currently open FOV
4. User selects a target FOV from the second dropdown
5. User clicks "Apply"
6. System reads source labels, creates a new segmentation run on target, writes labels, extracts cells
7. Status label shows "Copied N cells from FOV_001 to bg_sub_FOV_001"

## Scope

### In Scope
- Standalone `copy_labels_to_fov(store, source_fov_id, target_fov_id, channel)` function
- Napari dock widget with source/target dropdowns and apply button
- Dimension mismatch warning (but don't block)
- New segmentation run with provenance (`method: label_copy`, `source_fov_id`)
- Tests for the core copy function

### Out of Scope
- Automatic label copy when creating derived FOVs (future enhancement)
- Label transformation (scaling, cropping, re-numbering)
- Copying threshold masks or particle labels (only cell segmentation labels)
- CLI menu access (napari-only for now)
