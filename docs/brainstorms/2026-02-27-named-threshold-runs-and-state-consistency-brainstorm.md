---
topic: Named Threshold Runs and Zarr/SQLite State Consistency
date: 2026-02-27
status: deferred
---

# Named Threshold Runs and Zarr/SQLite State Consistency

## What We're Building

Transform the thresholding system from single-overwrite semantics to **multiple named threshold runs** per FOV+channel. Users can:
- Create named threshold runs (e.g., "strict", "liberal")
- Save over an existing named run (complete replacement)
- Select which threshold run to use for plugin analysis
- View/manage threshold runs in a list

This also addresses the Zarr/SQLite state mismatch issues (todos 119-133) by designing consistency into the multi-run system from the start.

## Why This Change

Current problems:
1. **Single-threshold limitation:** Only one threshold per FOV+channel. Re-thresholding destroys previous work.
2. **Use case: comparative analysis:** User wants to compare strict vs liberal thresholding on the same data, keeping both results.
3. **State mismatch bugs:** The current overwrite model causes stale particles, orphaned measurements, and Zarr/SQLite desynchronization (the recently fixed 0-intensity bug).

The multi-run design eliminates the state mismatch problem by giving each run its own dedicated storage space in both Zarr and SQLite.

## Key Decisions

- **Named runs:** Each threshold run gets a user-provided name (e.g., "strict_3.99", "liberal_31.7")
- **Name before thresholding:** User chooses "create new" or "overwrite existing" before starting the threshold workflow
- **Save-over = complete replacement:** Overwriting a named run deletes ALL associated data (particles, measurements, masks, plugin results) then writes fresh
- **One mask per run in Zarr:** Each threshold run stores its own mask in Zarr (e.g., `masks.zarr/fov_1/GFP/run_strict/`)
- **Plugin run selection:** Before running a plugin, user selects which threshold run to analyze against
- **Export per run:** CSV exports produce separate files per threshold run
- **Segmentation:** Single-run for now, but schema designed to support multi-segmentation later
- **Cleanup:** Save-over triggers atomic cleanup of all dependent data (particles, measurements, plugin outputs, Zarr masks)

## User Workflow

### Creating threshold runs
```
Threshold menu:
  Channel: GFP
  [1] Create new threshold run
  [2] Overwrite existing run
  [3] List/manage threshold runs

  > 1
  Name for this threshold run: strict
  [threshold interactively...]
  Saved as "strict" (run ID: 16)
```

### Selecting for analysis
```
Run split-halo-condensate analysis:
  Channel: GFP
  Available threshold runs:
    [1] strict (threshold=3.99, 2026-02-27 10:30)
    [2] liberal (threshold=31.70, 2026-02-27 11:15)
  Select threshold run: 1
  [runs analysis against "strict" particles...]
```

### Managing runs
```
Threshold runs for GFP:
  ID  Name      Threshold  Particles  Created
  16  strict    3.99       1,247      2026-02-27 10:30
  17  liberal   31.70      89         2026-02-27 11:15

  [1] Delete a run
  [2] Rename a run
  [3] Back
```

## Schema Changes Required

### threshold_runs table
Add columns:
- `fov_id INTEGER NOT NULL REFERENCES fovs(id)` — (addresses todo #123)
- `name TEXT NOT NULL` — user-provided name
- `UNIQUE(fov_id, channel_id, name)` — one name per FOV+channel

### masks.zarr layout
Change from: `masks.zarr/fov_{id}/{channel}/`
To: `masks.zarr/fov_{id}/{channel}/run_{run_id}/`

### particles table
Already has `threshold_run_id` — no change needed. Multiple runs' particles coexist naturally.

### measurements table
Plugin measurements need to know which threshold run they belong to. Options:
- Add `threshold_run_id` to measurements (cleanest, enables per-run cleanup)
- Use scope naming convention (e.g., `scope="mask_inside:strict"`) — hacky

## Relationship to State Mismatch Todos

| Todo | Status with Named Runs |
|------|----------------------|
| #119 Transaction safety gap | **Solved:** save-over uses atomic cleanup |
| #120 Stale mask_inside/mask_outside | **Solved:** per-run storage, save-over cleans all |
| #121 Bind param overflow | **Still needed:** batch safety for large FOVs |
| #122 Layering violation | **Still needed:** architectural fix |
| #123 Missing fov_id on threshold_runs | **Solved:** added in schema change |
| #124 Orphaned segmentation_runs | **Deferred:** segmentation stays single-run for now |
| #125 Missing composite index | **Still needed:** performance fix |
| #126 Missing ON DELETE CASCADE | **Partially solved:** new FKs get CASCADE |
| #127 Stale zarr masks on re-seg | **Deferred:** segmentation stays single-run |
| #128 analysis_runs disconnected | **Partially addressed:** threshold_run_id on measurements |
| #129 fov_status_cache stale | **Still needed:** cache must account for multiple runs |
| #130 N+1 cache update | **Still needed:** performance fix |

## Scope

### In Scope
- [ ] Add `fov_id` and `name` to `threshold_runs` schema
- [ ] Update Zarr mask layout to per-run paths
- [ ] Save-over with atomic cleanup (particles + measurements + masks)
- [ ] Create-new with name prompt
- [ ] Threshold run selection UI in menu
- [ ] Threshold run management (list, delete, rename)
- [ ] Plugin analysis selects threshold run
- [ ] Export produces separate files per threshold run
- [ ] Migration for existing experiments (assign default name to existing runs)

### Out of Scope
- Multi-segmentation (future consideration, schema compatible)
- Automatic re-analysis when threshold changes
- Threshold run comparison visualization
- Branching/versioning beyond threshold runs

## Resolved Questions

1. **Default name for auto-created runs:** Auto-increment: "run_1", "run_2", etc. User can rename later.
2. **Migration strategy:** Existing unnamed threshold runs get assigned the name "default" during migration.
