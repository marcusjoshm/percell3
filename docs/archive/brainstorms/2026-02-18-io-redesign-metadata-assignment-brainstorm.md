---
title: IO Redesign — Metadata Assignment and Import Flow
type: brainstorm
date: 2026-02-18
status: decided
---

# IO Redesign — Metadata Assignment and Import Flow

## What We're Building

A redesigned image import flow for PerCell 3 that uses a **table-first interactive approach** to assign metadata (condition, biological replicate, FOV) to scanned file groups. The design prioritizes:

1. **Single-cell focus**: Every design decision serves the goal of building a complete single-cell analysis platform where the experiment hierarchy (Condition > Bio Rep > FOV > Cell > Measurement) is explicit and managed.
2. **Incremental experiment building**: Experiments grow over time — new conditions, new replicates, new FOVs can be added at any point.
3. **Balance of automation and control**: Auto-detect what can be detected (channels, z-slices, file groups), let the user assign what requires judgment (conditions, bio reps).

## Why This Approach

### Table-First Interactive Import (chosen over Auto-Detect + Confirm and Config-File Driven)

**Rationale:**
- Directly matches the user's workflow: import from multiple conditions at once, assign metadata by selecting rows
- No regex or auto-detection magic that breaks with different microscope outputs
- Context-aware: when adding to an existing experiment, shows existing conditions and bio reps
- Handles the "build as you go" pattern naturally — from pilot experiments to multi-replicate studies

**What we learned from other tools:**
- CellProfiler's 4-module pipeline (Images → Metadata → NamesAndTypes → Groups) is powerful but overexposed. Users struggle with regex. PerCell 3 should do the same 4 steps internally but present them as a single flow.
- QuPath's simplicity (drag-and-drop, key-value metadata) is good for whole-slide images but lacks experiment hierarchy.
- OMERO has the closest hierarchy (Project > Dataset > Image) but treats conditions/replicates as ad-hoc annotations, not first-class entities.
- The scverse ecosystem (AnnData) demonstrates that cell-centric data models (one row per cell) are the right output format.
- **No single tool manages the full Condition > Bio Rep > FOV > Cell hierarchy.** PerCell 3 fills this gap.

## Key Decisions

### 1. Hierarchy Change: Condition > Bio Rep > FOV

**Current:** Bio Rep > Condition > FOV
**New:** Condition > Bio Rep > FOV

Rationale: Conditions are the primary experimental grouping. Each condition can have an uneven number of biological replicates. Example: Conditions A, B, C might have 2 bio reps while conditions D, E (added later) have only 1. This models real experimental workflows where pilots become first replicates.

**Clean break** — no migration needed. No production data exists.

### 2. Bio Replicates Always Tracked

Even pilot experiments get a bio replicate number (default N1). This enables:
- Going back to see how many times an experiment has been repeated
- Adding replicates later without restructuring
- Distinguishing biological replicates from technical replicates (FOVs)

Experiments represent a **methodology + sample type** and are reusable containers for accumulating replicates.

### 3. Table-First File Group Assignment

After scanning, display a numbered table:

```
  #  File group              Ch  Z   Files
  1  30min_Recovery_Merged     3  4    12
  2  1hr_Recovery_Merged       3  4    12
  3  Untreated_Merged          3  4    12
```

- Select groups by space-separated numbers or `all`
- Assign condition name (shows existing conditions as pick list if experiment has data)
- Assign bio replicate (defaults to N1, shows existing bio reps)
- Table updates to show assignments with Condition and Rep columns
- `done` exits the loop; unassigned groups are skipped
- Works for both first import and adding to existing experiments

### 4. FOV Numbering: Auto-Number with Optional Rename

- Default: FOV_001, FOV_002... sequentially within each (condition, bio rep) scope
- Incremental: adding FOVs to an existing condition/bio rep continues from the next number
- Optional rename available through Edit experiment menu

### 5. Channels: Auto-Detect + Rename Once

- Auto-detect channel tokens from filenames (_ch00, _ch01)
- Prompt to name channels once per experiment (DAPI, GFP, mCherry)
- Same channel names apply across all conditions/replicates

### 6. Additional Token Support

- **Time-points (_tXX)**: Time is a dimension of a FOV (like z-slices), not a separate FOV. Stored as an axis in the zarr array.
- **Tile positions (_sXX)**: Can be assigned as individual FOVs OR stitched into a single FOV. User chooses during import.

### 7. Context-Aware Prompts

When adding data to an existing experiment:
- Show existing conditions as a numbered pick list + "(new condition)" option
- Show existing bio replicates for the chosen condition
- Ask whether new files are a new bio replicate or additional FOVs for an existing one
- Auto-number FOVs from the next available number

### 8. Import Flow During "Add to Existing"

When the experiment already has data, the import prompt should ask:
- "Add new data to existing condition, or create new condition?"
- For existing condition: "New biological replicate, or additional FOVs for existing replicate?"
- This distinction matters for correct hierarchy placement

## Data Model Changes

```
Experiment (methodology + sample type, reusable container)
  └── Condition (control, treated_30min, treated_1hr...)
       └── Bio Replicate (N1, N2, N3...)
            └── FOV (FOV_001, FOV_002... — technical replicates)
                 └── Cell (segmented objects)
                      └── Measurement (channel x metric → value)
  └── Channels (DAPI, GFP, mCherry... — global to experiment)
```

### Schema Changes (clean break)

- `conditions` table: `id`, `experiment_id`, `name`
- `bio_reps` table: `id`, `condition_id`, `name` (e.g., "N1", "N2")
- `fovs` table: `id`, `bio_rep_id`, `name`, `width`, `height`
- `cells` table: unchanged (still references `fov_id`)
- `measurements` table: unchanged
- Remove old `bio_rep` column from `fovs` — bio_rep is now a parent entity

### Zarr Structure Change

```
experiment.percell/
  images/
    {condition}/
      {bio_rep}/
        {fov}/
          .zarray (channels, [time], [z], y, x)
  labels/
    {condition}/
      {bio_rep}/
        {fov}/
          .zarray
```

## Open Questions

*None — all questions resolved during brainstorm dialogue.*

## Resolved Questions

1. **Import scenario**: Multiple conditions at once (not one at a time)
2. **Assignment UX**: Table-first (not auto-detect, not hybrid)
3. **FOV numbering**: Auto-number with option to rename
4. **Bio rep importance**: Essential during import, always tracked from day one
5. **Hierarchy order**: Condition > Bio Rep > FOV (not Bio Rep > Condition)
6. **Adding replicates**: Conditions can have uneven numbers of bio reps
7. **Channels**: Auto-detect + rename once per experiment
8. **Existing data**: Clean break, no migration needed
9. **Table UX**: Numbered list, space-separated selection, updates after each assignment
10. **Time-points**: Dimension of FOV (like z), not separate FOVs
11. **Tile positions**: Can be individual FOVs or stitched, user chooses
12. **Adding to existing**: Context-aware prompts showing what exists

## References

- [CellProfiler Input Modules Documentation](https://cellprofiler-manual.s3.amazonaws.com/CellProfiler-4.0.5/modules/input.html)
- [QuPath Projects Tutorial](https://qupath.readthedocs.io/en/stable/docs/tutorials/projects.html)
- [OMERO Data Management Guide](https://omero-guides.readthedocs.io/projects/introduction/en/latest/data-management.html)
- [Squidpy Documentation](https://squidpy.readthedocs.io/)
- [OME-Zarr Specification](https://ngff.openmicroscopy.org/)
- Previous brainstorm: `docs/brainstorms/2026-02-17-data-model-bio-rep-fov-restructure-brainstorm.md`
- Previous brainstorm: `docs/brainstorms/2026-02-12-io-module-design-brainstorm.md`
