# Brainstorm: Per-Condition Channel Support

**Date:** 2026-02-24
**Status:** Deferred
**Scope:** Data model, import flow, CLI, downstream consumers

---

## What We're Building

PerCell 3 currently treats channels as experiment-global: every condition and FOV
shares the same flat list of channels. This breaks when conditions were imaged with
different filter sets or different numbers of channels — e.g., WT has `[DAPI, m7G_Cap, GFP]`
while KO has `[DAPI, m7G_Cap, mCherry]`.

We need per-condition channel declarations so that:
- Each condition explicitly lists which channels it has.
- Shared channels (DAPI, m7G_Cap) are the same `channels` row — measurements compare cleanly.
- Condition-specific channels (GFP, mCherry) coexist without conflict.
- The UI prevents invalid operations (e.g., measuring GFP in a KO condition that lacks it).

## Why This Approach

**Approach A: `condition_channels` join table** was selected over two alternatives:

- **vs. FOV-level presence (B):** Channels vary by condition, not by individual FOV.
  Per-FOV tracking is overkill and harder to reason about.
- **vs. Channel groups (C):** Adds an extra indirection layer (groups) without clear
  benefit. The join table is simpler and maps directly to the domain.

The join table is explicit, query-friendly, and keeps the data model condition-centric.

## Key Decisions

### 1. Data Model: `condition_channels` Join Table

```sql
CREATE TABLE condition_channels (
    condition_id INTEGER NOT NULL REFERENCES conditions(id),
    channel_id   INTEGER NOT NULL REFERENCES channels(id),
    display_order INTEGER NOT NULL,  -- C-axis index for this condition
    PRIMARY KEY (condition_id, channel_id)
);
```

- Channels remain experiment-global in the `channels` table (unique name, one row per
  distinct channel name).
- Each condition declares its own subset of channels with a per-condition `display_order`
  for zarr C-axis indexing.
- Shared channels (e.g., DAPI) reference the same `channels.id` across conditions.

### 2. Zarr Storage: Variable C Per FOV

Each FOV's zarr array has shape `(C_condition, Y, X)` where `C_condition` is the number
of channels for that FOV's condition — no zero-padding.

- `read_image_numpy(fov_id, channel)` resolves the C-index via the condition's
  `display_order` in `condition_channels`, not the global `channels.display_order`.
- Writing similarly uses the condition's display_order.
- The global `channels.display_order` becomes a presentation-only field (menu ordering).

### 3. Import Flow: Name Per Condition Import

Each condition's import is a separate naming step:

1. User imports TIFFs for a condition.
2. Scanner finds channel tokens (e.g., `ch00`, `ch01`).
3. User assigns names to each token for *this condition*.
4. If a name matches an existing `channels` row, it's reused (linked).
   If it's new, a new `channels` row is created.
5. The `condition_channels` table is populated with the mappings.

On subsequent imports for the same condition, existing channel mappings are shown
and auto-matched.

### 4. UI Principle: Condition First, Then Channel Intersection

For all operations that involve channel selection (measurement, threshold, BG subtraction,
export):

1. **Step 1:** Select conditions to operate on.
2. **Step 2:** Channel picker shows only the **intersection** of channels available
   across the selected conditions.

This prevents invalid selections entirely — the user can never pick a channel that
doesn't exist for one of the selected conditions.

### 5. Error Handling: Skip With Warning

When an operation iterates over channels and encounters a FOV whose condition lacks
that channel:

- **Skip the measurement/operation** for that channel on that FOV.
- **Log a warning** so the user knows some cells were skipped.
- **Do not crash** — graceful degradation.

This is a safety net. The UI-level prevention (Decision 4) should make this rare.

### 6. Segmentation Channel: Per-Condition

Different conditions may use different segmentation channels. The `segmentation_runs`
table already references `channel_id`, so this works naturally — each condition's
segmentation run can reference a different channel. No schema change needed for this.

### 7. No Migration — Breaking Change

The app is still in development. Existing experiments will not be migrated.
Old experiments created before this change will need to be re-created.
The `condition_channels` table will be part of the schema from the start for
new experiments.

## Affected Modules

| Module | Impact |
|--------|--------|
| **core/schema.py** | Add `condition_channels` table, migration logic |
| **core/experiment_store.py** | New methods: `add_condition_channel()`, `get_condition_channels()`, `get_common_channels()`. Modify `read_image_numpy`/`write_image` to resolve C-index per condition. |
| **core/zarr_io.py** | Variable C-axis per FOV group. Resolve channel index via condition, not global display_order. |
| **io/engine.py** | Populate `condition_channels` during import. |
| **cli/menu.py** | Import: per-condition channel naming. Operations: condition-first selection, then channel intersection. |
| **measure/** | Measurer, ThresholdEngine, ParticleAnalyzer: check channel existence for condition before reading. |
| **plugins/** | BG subtraction and future plugins: respect per-condition channels. |
| **export** | CSV/Prism export: handle sparse channel columns across conditions. |

## Pre-Implementation Prerequisite

- **NGFF viewer compatibility:** Verify that napari and FIJI handle per-FOV variable
  channel lists correctly (different FOVs having different C dimensions and different
  `omero.channels` metadata). If they don't, a compatibility shim may be needed
  (e.g., padding metadata without padding pixel data). This must be tested before
  committing to the variable-C zarr layout.

## Resolved Questions

1. **Channel rename with join table:** `rename_channel()` updates `channels.name` and
   zarr metadata. The join table references `channel_id` (integer FK), so renames
   propagate automatically — no join table changes needed.

2. **Re-import behavior:** If a condition already has channel mappings and the user
   re-imports with different channel names, **error and refuse**. The user must delete
   the condition first and re-import from scratch. This prevents accidental data
   corruption from mismatched channel assignments.
