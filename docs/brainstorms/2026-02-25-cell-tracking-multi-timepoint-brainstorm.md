---
title: "Cell Tracking for Multi-Timepoint Datasets — LapTrack Overlap-Based Tracking"
type: feat
date: 2026-02-25
status: deferred
---

# Cell Tracking for Multi-Timepoint Datasets

## What We're Building

Automatic cell tracking that runs as part of the segmentation pipeline whenever multiple timepoints are detected. When a dataset has >1 timepoint, the system will:

1. Segment all timepoints normally via Cellpose
2. Automatically run overlap-based cell tracking using LapTrack's `OverLapTrack`
3. Store track assignments (track ID, lineage tree, division events) in SQLite
4. Make track IDs available in all downstream analysis and exports

This is a **core module** (`src/percell3/track/`), not a plugin, because tracking is fundamental to multi-timepoint analysis and should always run when timepoints exist.

## Why This Approach

### Why overlap-based tracking (not centroid-only)?

The original PerCell used centroid-based nearest-neighbor matching with the Hungarian algorithm. This works for simple cases but has significant limitations:

- **No division detection** — when a cell divides, both daughters are marked "incomplete"
- **No gap closing** — cells that disappear for one frame can't be re-linked
- **Shape-blind** — two cells with similar centroids but very different shapes can be mis-linked
- **Pairwise-only** — no global optimization across track segments

LapTrack's `OverLapTrack` solves all of these by:
- Using label image overlap (IoU) instead of centroid distance
- Implementing the full Jaqaman LAP framework (two-stage: frame linking + segment linking)
- Supporting division detection with a separate splitting cost
- Supporting gap closing across configurable frame counts
- Directly consuming label images from `labels.zarr` (no data conversion needed)

### Why a core module (not a plugin)?

The user will always want tracking for multi-timepoint data. Making it automatic avoids a manual step that could be forgotten. The CLAUDE.md principle "plugins over hardcoded stages" applies to optional analysis routines — tracking is not optional when timepoints exist.

### Why LapTrack specifically?

| Library | Division support | Dependencies | Label image input | Gap closing |
|---------|-----------------|--------------|-------------------|-------------|
| **LapTrack** | Yes (built-in) | Pure Python + scipy | Yes (`OverLapTrack`) | Yes |
| trackpy | No | numpy, pandas | No (centroids only) | Yes (memory) |
| btrack | Yes | C++ compilation | Yes | Yes |
| DIY scipy | No | None (scipy) | Manual | No |

LapTrack is the best fit: handles divisions, consumes label images directly, pure Python (no compilation), lightweight, and published in Bioinformatics (2023).

**Reference:** [LapTrack paper](https://academic.oup.com/bioinformatics/article/39/1/btac799/6887138), [GitHub](https://github.com/yfukai/laptrack)

## Key Decisions

### 1. Algorithm — LapTrack OverLapTrack

**Decision:** Use `laptrack.OverLapTrack` as the tracking algorithm. It consumes sequences of label images and returns track DataFrames with division/merge events.

**How it works:**

Stage 1 — Frame-to-frame linking:
- For each pair of consecutive frames, compute overlap between all label pairs
- Build a cost matrix where cost = 1 - IoU (or configurable metric coefficients)
- Solve with the Hungarian algorithm
- Unmatched labels become track starts/terminations

Stage 2 — Track segment linking:
- After stage 1, short track segments exist
- Build a second cost matrix to connect segments: gap closing (missed detection), splitting (division), merging (undersegmentation artifact)
- Solve globally to produce final track assignments

**Parameters (user-configurable):**
- `max_distance` (float, default 50.0): Maximum centroid displacement for overlap search pruning
- `min_iou` (float, default 0.1): Minimum IoU for a valid link (maps to `cutoff` in LapTrack)
- `splitting_min_iou` (float, default 0.1): Minimum overlap for division detection
- `gap_frames` (int, default 1): Maximum frames a cell can disappear and be re-linked

**PerCell reference:** Original tracking at `percell/application/image_processing_tasks.py:2548-2653` used centroid-based Hungarian matching with `max_distance=50.0`.

### 2. Dependency — Required in pyproject.toml

**Decision:** Add `laptrack>=0.6` to core dependencies. It's pure Python with only scipy/numpy as transitive dependencies (both already installed).

```toml
# pyproject.toml
dependencies = [
    # ... existing deps ...
    "laptrack>=0.6",
]
```

### 3. Storage — New SQLite Tables

**Decision:** Add `tracking_runs` and `tracks` tables to the core schema. Track assignments are non-destructive — original cell records and label images are never modified.

```sql
CREATE TABLE IF NOT EXISTS tracking_runs (
    id INTEGER PRIMARY KEY,
    algorithm TEXT NOT NULL,           -- 'laptrack_overlap'
    parameters TEXT,                   -- JSON blob of algorithm parameters
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY,
    tracking_run_id INTEGER NOT NULL REFERENCES tracking_runs(id),
    track_id INTEGER NOT NULL,         -- LapTrack-assigned track ID
    tree_id INTEGER,                   -- Lineage tree ID (shared by parent + descendants)
    cell_id INTEGER NOT NULL REFERENCES cells(id),
    parent_track_id INTEGER,           -- NULL for founders, set on division
    generation INTEGER NOT NULL DEFAULT 0,
    event TEXT DEFAULT 'none',         -- 'none', 'division', 'appear', 'disappear'
    UNIQUE(tracking_run_id, cell_id)
);
```

**Key design choices:**
- `track_id` = same biological cell across timepoints. All cells in the same track share this ID.
- `tree_id` = lineage tree. A mother and both daughters share a tree_id but have different track_ids.
- `parent_track_id` = links daughter tracks to parent (set when `event='division'`).
- `generation` = division depth (0=founder, 1=first division, 2=second, etc.)
- Multiple tracking runs can coexist (different parameters, comparison).

**New dataclass:**
```python
@dataclass(frozen=True)
class TrackRecord:
    tracking_run_id: int
    track_id: int
    tree_id: int | None
    cell_id: int
    parent_track_id: int | None = None
    generation: int = 0
    event: str = "none"
```

### 4. Integration — Automatic After Segmentation

**Decision:** The segmentation engine (`segment/_engine.py`) will automatically invoke tracking after segmenting all FOVs when the experiment has multiple timepoints. The flow:

1. User runs segmentation (interactive menu or CLI)
2. Segmentation engine processes all FOVs, writes labels to zarr, inserts cells into DB
3. Engine checks: does this experiment have >1 timepoint?
4. If yes: automatically run tracking on all FOV groups (same condition + bio_rep, different timepoints)
5. Print tracking summary (tracks found, divisions detected, completeness)

**FOV grouping logic:** FOVs that share the same `(condition_id, bio_rep_id)` but differ in `timepoint_id` belong to the same tracking group. Each group is tracked independently.

**CLI flag:** `--no-track` to skip automatic tracking (for re-segmenting without re-tracking).

### 5. Module Structure

```
src/percell3/track/
├── __init__.py          # Public API: track_experiment(), TrackRecord
├── tracker.py           # Core tracking logic using LapTrack
└── quality.py           # Track quality metrics and reporting
```

**`tracker.py`** contains:
- `track_fov_group(store, fov_ids, params) -> TrackingResult` — tracks one group of FOVs
- `track_experiment(store, params) -> list[TrackingResult]` — tracks all FOV groups
- FOV grouping logic (group by condition + bio_rep, sort by timepoint)
- Label image loading from zarr, LapTrack invocation, result mapping to cell IDs

**`quality.py`** contains:
- Track completeness (% cells assigned to a track)
- Mean/median track length
- Division count
- Orphan rate (single-frame tracks)
- Console summary report

### 6. Export Integration

**Decision:** Track IDs should appear in all export formats as a `track_id` column. This uses the same pattern as the cell group export (join from the tracks table during export).

- Wide CSV: include `track_id` column per cell
- Per-cell metrics: include `track_id` column
- Prism format: `track_id` available as a grouping variable
- Particle metrics: include parent cell's `track_id`

## How PerCell Did It (Reference)

PerCell's tracking (`image_processing_tasks.py:2548-2653`):

1. **Algorithm:** Centroid-based Hungarian matching via `scipy.optimize.linear_sum_assignment`
2. **Distance matrix:** `scipy.spatial.distance.cdist` on ROI centroids (polygon centroid via shoelace formula)
3. **Threshold:** `max_distance=50.0` pixels — matches above this are "incomplete"
4. **Result storage:** Reordered ROI zip files so CELL1 = same cell across timepoints (destructive — overwrote originals, backed up to `roi_backups/`)
5. **Quality report:** `tracking_report.txt` with complete/incomplete track counts, per-track distances
6. **Limitations:** No division detection, no gap closing, no shape consideration, pairwise-only (no global segment linking)

**What PerCell 3 improves:**
- Shape-aware overlap matching instead of centroid-only
- Division detection via LapTrack's splitting cost
- Gap closing across frames
- Non-destructive storage (tracks table, not file reordering)
- Global optimization via two-stage LAP framework

## Resolved Questions

1. **Algorithm?** — LapTrack OverLapTrack (overlap-based, two-stage LAP)
2. **Dependency?** — Required (`laptrack>=0.6` in core deps)
3. **Storage?** — New `tracking_runs` + `tracks` SQLite tables
4. **Plugin or core?** — Core module (`src/percell3/track/`), always runs for multi-timepoint data
5. **Trigger?** — Automatic after segmentation when >1 timepoint exists
6. **Export?** — `track_id` column in all export formats
7. **Division handling?** — Built into LapTrack, stored via `parent_track_id` + `event='division'`
8. **FOV grouping?** — Group by (condition_id, bio_rep_id), sort by timepoint display_order
