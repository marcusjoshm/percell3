---
title: "feat: Per-Condition Channel Support"
type: feat
date: 2026-02-24
status: deferred
brainstorm: docs/brainstorms/2026-02-24-per-condition-channels-brainstorm.md
---

# Per-Condition Channel Support

## Overview

Add a `condition_channels` join table so each condition explicitly declares which
channels it has. Channels remain experiment-global (shared names reuse the same
`channels` row), but each condition gets its own subset with a per-condition
`display_order` for zarr C-axis indexing. FOVs store variable-C arrays matching
their condition's channel count.

This enables experiments where conditions were imaged with different filter sets
or different numbers of channels (e.g., WT has `[DAPI, m7G_Cap, GFP]` while KO
has `[DAPI, m7G_Cap, mCherry]`).

## Problem Statement

Channels are currently experiment-global: the `channels` table has `UNIQUE(name)`
with no condition scoping. All FOVs get the same C-dimension in zarr. This breaks
when conditions have different channel sets -- importing condition B with fewer
channels either wastes zarr space (empty C-slots) or fails entirely if names
don't match.

## Proposed Solution

A `condition_channels(condition_id, channel_id, display_order)` join table links
conditions to their channels. The zarr C-axis uses the condition-specific
`display_order`. All UI operations use a condition-first selection pattern: pick
conditions, then pick channels from their intersection.

## Pre-Implementation Prerequisite

Before committing to variable-C zarr layout, verify that napari and FIJI handle
per-FOV variable channel lists correctly. Test by manually creating a zarr store
with two FOV groups having different C dimensions and `omero.channels` metadata.

---

## Technical Approach

### Architecture

```mermaid
erDiagram
    conditions ||--o{ condition_channels : has
    channels ||--o{ condition_channels : "belongs to"
    conditions ||--o{ fovs : contains
    condition_channels {
        int condition_id PK FK
        int channel_id PK FK
        int display_order
    }
    channels {
        int id PK
        text name UK
        text role
        int display_order "presentation only"
    }
    conditions {
        int id PK
        text name UK
    }
    fovs {
        int id PK
        int condition_id FK
    }
```

**Key invariant:** A FOV's zarr array has shape `(C, Y, X)` where `C` equals
the number of `condition_channels` rows for that FOV's condition. The
`condition_channels.display_order` maps channel name to C-index.

### Implementation Phases

---

#### Phase 1: Schema and Query Layer

Add the `condition_channels` table and query functions. No behavior changes yet --
existing code continues to work because the table is simply empty/unused.

##### 1.1 Schema (`src/percell3/core/schema.py`)

Add DDL after the `conditions` table:

```sql
CREATE TABLE IF NOT EXISTS condition_channels (
    condition_id INTEGER NOT NULL REFERENCES conditions(id) ON DELETE CASCADE,
    channel_id   INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    display_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (condition_id, channel_id)
);
CREATE INDEX IF NOT EXISTS idx_condition_channels_channel
    ON condition_channels(channel_id);
```

- Add `"condition_channels"` to `EXPECTED_TABLES`
- Add `"idx_condition_channels_channel"` to `EXPECTED_INDEXES`
- Bump `EXPECTED_VERSION` to `"3.5.0"`

##### 1.2 Query Functions (`src/percell3/core/queries.py`)

```python
def insert_condition_channel(
    conn, condition_id: int, channel_id: int, display_order: int,
) -> None

def select_condition_channels(
    conn, condition_id: int,
) -> list[ChannelConfig]
    """Channels for one condition, ordered by display_order."""

def select_channel_intersection(
    conn, condition_ids: list[int],
) -> list[ChannelConfig]
    """Channels common to ALL given conditions."""

def select_conditions_for_channel(
    conn, channel_id: int,
) -> list[int]
    """Condition IDs that have this channel."""

def get_condition_channel_display_order(
    conn, condition_id: int, channel_id: int,
) -> int
    """C-axis index for a channel within a condition."""
```

##### 1.3 ExperimentStore Methods (`src/percell3/core/experiment_store.py`)

```python
def add_condition_channel(
    self, condition: str, channel: str, display_order: int,
) -> None

def get_condition_channels(
    self, condition: str,
) -> list[ChannelConfig]

def get_channel_intersection(
    self, conditions: list[str],
) -> list[ChannelConfig]

def has_condition_channels(self, condition: str) -> bool
    """True if condition has any channel mappings."""
```

Keep `get_channels()` returning all experiment-global channels (backward compat).

##### 1.4 Tests (`tests/test_core/`)

- `test_schema.py`: New table and index appear in `EXPECTED_TABLES`/`EXPECTED_INDEXES`
- `test_queries.py`: CRUD for `condition_channels`, intersection logic, edge cases
  (empty intersection, single condition, condition with no channels)
- `test_experiment_store.py`: `add_condition_channel()`, `get_condition_channels()`,
  `get_channel_intersection()`, `has_condition_channels()`

##### Phase 1 Acceptance Criteria

- [ ] `condition_channels` table created by schema init
- [ ] `insert_condition_channel` + `select_condition_channels` round-trip
- [ ] `select_channel_intersection` returns correct intersection
- [ ] `select_channel_intersection` with no common channels returns empty list
- [ ] `ON DELETE CASCADE` works for both condition and channel deletion
- [ ] `pytest tests/test_core/ -v` passes

---

#### Phase 2: Zarr Read/Write with Per-Condition Channels

Modify `write_image()` and `read_image_numpy()` to resolve C-index and C-dimension
from `condition_channels` instead of global `channels.display_order`.

##### 2.1 ExperimentStore Changes (`src/percell3/core/experiment_store.py`)

**`write_image(self, fov_id, channel, data)`** — change from:
```python
ch = self.get_channel(channel)
channels = self.get_channels()
zarr_io.write_image_channel(
    ..., channel_index=ch.display_order, num_channels=len(channels), ...
)
```
to:
```python
fov = self.get_fov_by_id(fov_id)
condition_channels = self.get_condition_channels(fov.condition)
ch = self.get_channel(channel)
c_index = self._condition_channel_index(fov.condition, ch.id)
zarr_io.write_image_channel(
    ..., channel_index=c_index, num_channels=len(condition_channels),
    channels_meta=self._condition_channels_meta(fov.condition), ...
)
```

**`read_image_numpy(self, fov_id, channel)`** — same pattern: resolve C-index
via condition, not global display_order.

**`_condition_channels_meta(self, condition)`** — new helper returning NGFF
metadata for only that condition's channels (name, color).

**`_condition_channel_index(self, condition, channel_id)`** — looks up
`display_order` from `condition_channels` for this condition+channel.

**Fallback for experiments without condition_channels:** If `condition_channels`
is empty for a condition, fall back to the global `channels.display_order` behavior.
This provides a transition path where old-style experiments still work until
re-created.

##### 2.2 Tests

- Write image for condition A (3 channels), read back, verify correct data
- Write image for condition B (2 channels), verify FOV has shape `(2, Y, X)`
- Read channel from wrong condition raises error or returns correct data
- NGFF metadata per FOV matches condition's channels, not global list
- Fallback: experiment with no `condition_channels` rows uses global behavior

##### Phase 2 Acceptance Criteria

- [ ] FOV zarr arrays have shape `(C_condition, Y, X)` matching condition channel count
- [ ] `read_image_numpy` resolves correct C-index per condition
- [ ] NGFF `omero.channels` metadata lists only the condition's channels per FOV
- [ ] Global fallback works for experiments without `condition_channels` data
- [ ] `pytest tests/test_core/ -v` passes

---

#### Phase 3: Import Engine

Update the import pipeline to populate `condition_channels` during import and
enforce re-import rules.

##### 3.1 ImportEngine Changes (`src/percell3/io/engine.py`)

After channel registration (existing `add_channel` loop), add condition-channel
association:

```python
# After all channels are registered for this import batch:
condition_id = store.get_condition_id(condition_name)
if store.has_condition_channels(condition_name):
    # Validate incoming channels match existing
    existing = {ch.name for ch in store.get_condition_channels(condition_name)}
    incoming = {channel_name_map.get(t, sanitize_name(f"ch{t}")) for t in scan_result.channels}
    if existing != incoming:
        raise ImportError(
            f"Condition '{condition_name}' already has channels {sorted(existing)}. "
            f"Incoming channels {sorted(incoming)} do not match. "
            "Delete the condition first to re-import with different channels."
        )
else:
    # First import for this condition — create associations
    for order, ch_token in enumerate(sorted(scan_result.channels)):
        ch_name = channel_name_map.get(ch_token, sanitize_name(f"ch{ch_token}"))
        store.add_condition_channel(condition_name, ch_name, display_order=order)
```

##### 3.2 CLI Import Flow (`src/percell3/cli/menu.py`)

Update `_auto_match_channels()` to be condition-aware:
- On first import for a condition: name channels freely
- On subsequent imports for the same condition: auto-match against that condition's
  existing channels, error if mismatch

##### 3.3 Tests

- Import condition A with 3 channels, verify `condition_channels` populated
- Import condition B with 2 channels (1 shared), verify shared channel reused
- Re-import condition A with same channels, verify FOVs added successfully
- Re-import condition A with different channels, verify error raised
- Import with no channel tokens (default `ch0`), verify condition association

##### Phase 3 Acceptance Criteria

- [ ] First import for a condition creates `condition_channels` entries
- [ ] Shared channel names across conditions reuse the same `channels.id`
- [ ] Re-import with exact same channels adds FOVs without error
- [ ] Re-import with different channels raises `ImportError`
- [ ] Zarr arrays written with correct per-condition C-dimension
- [ ] `pytest tests/test_io/ tests/test_core/ -v` passes

---

#### Phase 4: Condition-First UI Pattern

Add reusable CLI helpers for condition selection + channel intersection, then wire
into measurement, threshold, and plugin handlers.

##### 4.1 Reusable Helpers (`src/percell3/cli/menu.py`)

```python
def _select_conditions(store) -> list[str]:
    """Multi-select conditions. Auto-selects if only one exists."""

def _select_channels_for_conditions(
    store, conditions: list[str],
) -> list[str]:
    """Show intersection of channels across selected conditions.
    Error and return to condition picker if intersection is empty."""
```

##### 4.2 Wire Into Existing Handlers

**Measurement (`_measure_whole_cell`, `_measure_masked`):**
1. Add condition selection step before channel selection
2. Channel picker shows intersection only
3. When iterating FOVs, filter to selected conditions
4. Skip with warning if a FOV's condition lacks a channel (safety net)

**Threshold (`_apply_threshold`):**
1. Add condition selection before channel selection
2. Same intersection logic

**BG Subtraction (`_run_bg_subtraction`):**
1. Add condition selection as Step 1
2. Channel pickers (measurement, particle, exclusion, normalization) show intersection
3. FOV selection filtered to selected conditions

##### 4.3 Skip-With-Warning Safety Net

In `measure/measurer.py` `measure_fov()`:

```python
for channel in channels:
    try:
        image = store.read_image_numpy(fov_id, channel)
    except (ChannelNotFoundError, KeyError):
        logger.warning("FOV %s: channel '%s' not available, skipping", fov_id, channel)
        continue
```

Same pattern in `measure_fov_masked()`, `ParticleAnalyzer.analyze_fov()`,
and `LocalBGSubtractionPlugin.run()`.

##### 4.4 Tests

- Condition picker with 1 condition auto-selects
- Condition picker with 3 conditions returns user selection
- Channel intersection of 2 overlapping conditions shows common channels only
- Channel intersection of non-overlapping conditions shows error message
- Measurement skips channels not in FOV's condition with warning

##### Phase 4 Acceptance Criteria

- [ ] All channel-selecting operations use condition-first pattern
- [ ] Channel picker shows intersection of selected conditions only
- [ ] Empty intersection shows error and returns to condition picker
- [ ] Operations skip missing channels with logged warning
- [ ] `pytest tests/ -v` passes (full suite)

---

#### Phase 5: Export and Plugin Updates

Update export and plugin code to handle per-condition channels.

##### 5.1 CSV Export (`src/percell3/core/experiment_store.py`)

`export_csv()` and `get_measurement_pivot()`:
- Channels that don't exist in all conditions produce empty cells in those rows
- This is the natural behavior of a LEFT JOIN pivot -- no code change needed
  if the query already handles missing measurements as NULL

##### 5.2 Prism Export

`export_prism_csv()`:
- Per (channel, metric) CSV: if a condition doesn't have that channel, omit
  that condition's column entirely (no empty columns)
- Add a check: skip conditions that lack the channel being exported

##### 5.3 BG Subtraction Plugin (`src/percell3/plugins/builtin/local_bg_subtraction.py`)

- `validate()`: check that required channels exist in at least one condition
- `run()`: already receives `cell_ids` filtered by the CLI handler's condition
  selection, so it naturally only processes FOVs whose condition has the channels
- The skip-with-warning safety net from Phase 4 handles edge cases

##### 5.4 Experiment Summary Query

Update `select_experiment_summary()` in `queries.py` to include per-condition
channel information so users can see which channels belong to which condition.

##### Phase 5 Acceptance Criteria

- [ ] CSV export handles sparse channel columns (empty for missing)
- [ ] Prism export omits condition columns for channels they lack
- [ ] BG subtraction works correctly with per-condition channels
- [ ] Experiment summary shows per-condition channel info
- [ ] `pytest tests/ -v` passes (full suite)

---

#### Phase 6: Cleanup and Edge Cases

##### 6.1 Channel Rename

Verify `rename_channel()` works correctly:
- `condition_channels` references `channel_id` (FK), so renames propagate automatically
- NGFF metadata update must now iterate only FOVs belonging to conditions that have
  that channel (optimization, not correctness -- the current global update also works)

##### 6.2 Condition Deletion

`ON DELETE CASCADE` on `condition_channels.condition_id` handles cleanup automatically.
Orphaned channels (channels with no `condition_channels` entries) are kept -- they
can be reused by future imports.

##### 6.3 Global `channels.display_order`

Repurpose as presentation-only ordering for menus/UI. It no longer controls zarr
C-index (that's `condition_channels.display_order`). No schema change needed --
just update documentation/comments.

##### 6.4 Edge Case Tests

- Condition with zero channels: allowed, but no images can be written/read
- Deleting a condition cascades to `condition_channels`, FOVs unaffected
  (FK violation prevents condition deletion if FOVs exist -- this is correct)
- Channel used by one condition: deleting that condition orphans the channel
- Re-import exact match: adds FOVs, does not duplicate `condition_channels`

##### Phase 6 Acceptance Criteria

- [ ] `rename_channel()` works across conditions
- [ ] Condition deletion cascades correctly
- [ ] Edge cases handled without crashes
- [ ] Full test suite passes: `pytest tests/ -v`

---

## Acceptance Criteria

### Functional Requirements

- [ ] Each condition declares its own channel set via `condition_channels`
- [ ] Shared channels (e.g., DAPI) are the same `channels` row across conditions
- [ ] FOV zarr arrays have `C = condition's channel count` (no zero-padding)
- [ ] Import names channels per condition, creates associations
- [ ] Re-import with exact same channels adds FOVs; different channels = error
- [ ] All channel-selecting UI operations use condition-first, then intersection
- [ ] Empty channel intersection shows error, returns to condition picker
- [ ] Operations skip missing channels with warning (safety net)
- [ ] CSV/Prism export handles sparse channel columns correctly

### Non-Functional Requirements

- [ ] No migration needed -- breaking change, old experiments re-created
- [ ] Global fallback for experiments without `condition_channels` data
- [ ] All existing tests continue to pass
- [ ] New tests cover per-condition channel CRUD, intersection, import, zarr I/O

### Quality Gates

- [ ] `pytest tests/ -v` -- full suite green
- [ ] Manual test: import 2 conditions with different channels, measure, export

---

## Risk Analysis

| Risk | Impact | Mitigation |
|------|--------|------------|
| Zarr C-index corruption from wrong display_order | Data loss | Thorough tests with multi-condition synthetic experiments |
| NGFF viewers can't handle variable-C per FOV | Broken napari viewing | Pre-implementation test (prerequisite) |
| Cascading API breaks across modules | Large diff, hard to review | Phase-by-phase implementation with tests at each gate |
| Import engine re-import detection too strict/loose | User frustration | Exact-match rule is simple and predictable |

## File Summary

| File | Changes |
|------|---------|
| `src/percell3/core/schema.py` | Add `condition_channels` table, bump version |
| `src/percell3/core/queries.py` | Add 5 query functions for condition_channels |
| `src/percell3/core/experiment_store.py` | Add 4 methods, refactor `write_image`/`read_image_numpy` |
| `src/percell3/core/zarr_io.py` | No changes (already receives channel_index as param) |
| `src/percell3/io/engine.py` | Populate condition_channels during import, re-import validation |
| `src/percell3/cli/menu.py` | Condition-first helpers, wire into all handlers |
| `src/percell3/measure/measurer.py` | Skip-with-warning for missing channels |
| `src/percell3/measure/particle_analyzer.py` | Same skip-with-warning pattern |
| `src/percell3/plugins/builtin/local_bg_subtraction.py` | Validate channels per condition |
| `tests/test_core/*` | Schema, query, store tests for condition_channels |
| `tests/test_io/*` | Import with per-condition channels |
| `tests/test_plugins/*` | Plugin with per-condition channels |

## References

- Brainstorm: `docs/brainstorms/2026-02-24-per-condition-channels-brainstorm.md`
- Current schema: `src/percell3/core/schema.py:24-33` (channels table)
- C-index resolution: `src/percell3/core/experiment_store.py:316-330` (write_image)
- Import engine: `src/percell3/io/engine.py:61-83` (channel registration)
- Channel picker: `src/percell3/cli/menu.py:1653-1727` (_auto_match_channels)
- Learnings: `docs/solutions/integration-issues/napari-viewer-datamodel-merge-api-conflicts.md`
  (cascading API breaks from data model changes)
- Learnings: `docs/solutions/design-gaps/import-flow-table-first-ui-and-heuristics.md`
  (import flow channel assignment gaps)
