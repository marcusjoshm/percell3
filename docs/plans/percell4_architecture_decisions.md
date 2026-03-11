# PerCell4 Architecture Design Decisions
*Consolidated context for coding agent — reflects all decisions made in design sessions*

---

## Project Scope

- **Type:** Lab-shared desktop analysis software, not a single-user app
- **Team size:** 3–6 researchers, each running local `.percell` files
- **Key capability:** `.percell` files are designed to be merged across machines for combined analysis
- **Planned ML feature:** Export image/label pairs for training particle detection models
- **UI target:** Napari plugin as primary interface, CLI for batch/headless automation
- **Not:** A web app, a server app, or a concurrent multi-writer system

---

## Database Engine

**SQLite in WAL mode.** DuckDB is overkill for expected data volumes. SQLite with proper indexing handles millions of measurement rows. One database file per `.percell` experiment.

Every connection must be configured immediately after open:

```python
def _configure_connection(self, conn: sqlite3.Connection):
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")  # Safe with WAL, 2-3x faster writes
    conn.execute("PRAGMA cache_size=-64000")    # 64MB cache
    conn.row_factory = sqlite3.Row
    # Debug helper — makes UUIDs readable in manual SQL sessions
    conn.create_function('uuid_str', 1, lambda b: str(uuid.UUID(bytes=b)) if b else None)
```

This must be called on every `sqlite3.connect()` — PRAGMA settings are not persisted.

**Debug views** for manual SQL inspection of ALL entity tables (created once at schema init):

```sql
CREATE VIEW debug_rois AS
SELECT uuid_str(id) AS id_hex, uuid_str(fov_id) AS fov_hex,
       uuid_str(roi_type_id) AS type_hex, label_id, area_px
FROM rois;

CREATE VIEW debug_fovs AS
SELECT uuid_str(id) AS id_hex, display_name, auto_name, status,
       uuid_str(parent_fov_id) AS parent_hex
FROM fovs;

CREATE VIEW debug_measurements AS
SELECT uuid_str(id) AS id_hex, uuid_str(roi_id) AS roi_hex,
       uuid_str(channel_id) AS channel_hex, metric, value, scope,
       uuid_str(pipeline_run_id) AS run_hex
FROM measurements;

CREATE VIEW debug_cell_identities AS
SELECT uuid_str(id) AS id_hex, uuid_str(experiment_id) AS exp_hex,
       uuid_str(origin_fov_id) AS origin_fov_hex, origin_label_id
FROM cell_identities;

CREATE VIEW debug_segmentation_sets AS
SELECT uuid_str(id) AS id_hex, name, seg_type, source_channel,
       uuid_str(produces_roi_type_id) AS roi_type_hex, fov_count
FROM segmentation_sets;

CREATE VIEW debug_fov_segmentation_assignments AS
SELECT uuid_str(id) AS id_hex, uuid_str(fov_id) AS fov_hex,
       uuid_str(segmentation_set_id) AS seg_hex, is_active, assigned_by
FROM fov_segmentation_assignments;

CREATE VIEW debug_fov_mask_assignments AS
SELECT uuid_str(id) AS id_hex, uuid_str(fov_id) AS fov_hex,
       uuid_str(threshold_mask_id) AS mask_hex, purpose, is_active
FROM fov_mask_assignments;
```

---

## ID Strategy

**UUID stored as BLOB(16) for all entity tables.**

**Do not use integer primary keys for entity tables.** Reasons:
- Database merging is a first-class feature — integer IDs collide across files
- ML training data requires globally stable, cross-file identifiers
- Multi-user provenance must survive merges intact
- `INSERT OR IGNORE` merge strategy requires UUID uniqueness guarantees

**Use integer IDs only for:**
- Append-only log tables (`fov_status_log`, `pipeline_run_log`)
- Junction tables with no external identity (`cell_group_assignments`, `group_members`)

**UUID helpers — use these everywhere, never write ad hoc:**

```python
import uuid

def new_uuid() -> bytes:
    return uuid.uuid4().bytes

def uuid_to_str(b: bytes) -> str:
    return str(uuid.UUID(bytes=b))

def str_to_uuid(s: str) -> bytes:
    return uuid.UUID(s).bytes
```

**Merge strategy:**

```python
def merge_experiment(source_path: str, target_db: Connection):
    target_db.execute("ATTACH ? AS source", (source_path,))  # Parameter binding, not f-string
    target_db.execute("PRAGMA foreign_keys=OFF")  # Self-referential FKs make ordering impossible
    for table in MERGE_TABLE_ORDER:  # Topologically sorted constant
        assert table.isidentifier()
        target_db.execute(f"INSERT OR IGNORE INTO {table} SELECT * FROM source.{table}")
    # Post-merge validation
    assert not target_db.execute("PRAGMA foreign_key_check").fetchall()
    target_db.execute("PRAGMA foreign_keys=ON")
    target_db.execute("DETACH source")
```

`INSERT OR IGNORE` is idempotent -- merging the same file twice produces no duplicates. See "Merge Strategy (S2)" section below for full implementation with conflict checks, cycle detection, and assignment conflict handling.

---

## ROI Table Strategy

**Unified `rois` table with `roi_type_id` FK to `roi_type_definitions`.**

**Do not create separate tables per ROI type.** Workflows routinely produce 3+ named sub-cellular ROI types per experiment (e.g. P-bodies, out-of-focus P-bodies, dilute phase foci). These types are experiment-specific and not hardcodeable. Separate tables would require N identical measurement code paths and new tables per experiment.

### roi_type_definitions

```sql
CREATE TABLE roi_type_definitions (
    id             BLOB(16) PRIMARY KEY,
    experiment_id  BLOB(16) REFERENCES experiments(id),
    name           TEXT NOT NULL,        -- internal key: 'pbody', 'oofocus_pbody'
    display_name   TEXT,                 -- human label: 'P-bodies'
    parent_type_id BLOB(16) REFERENCES roi_type_definitions(id),
    -- NULL = top-level (cells). Set to cell type id for sub-cellular ROIs.
    color_hex      TEXT,
    description    TEXT,
    sort_order     INTEGER
);
```

Populated from TOML `[[roi_types]]` on experiment creation. Each segmentation config in TOML declares `produces_roi_type`.

### rois

```sql
CREATE TABLE rois (
    id                  BLOB(16) PRIMARY KEY,
    roi_type_id         BLOB(16) REFERENCES roi_type_definitions(id),
    cell_identity_id    BLOB(16) REFERENCES cell_identities(id),
    parent_roi_id       BLOB(16) REFERENCES rois(id),
    segmentation_set_id BLOB(16) REFERENCES segmentation_sets(id),
    fov_id              BLOB(16) REFERENCES fovs(id),
    label_id            INTEGER,
    bbox_x INTEGER, bbox_y INTEGER, bbox_w INTEGER, bbox_h INTEGER,
    polygon             TEXT,   -- JSON
    area_px             INTEGER
);

CREATE INDEX idx_rois_fov_type ON rois(fov_id, roi_type_id);
CREATE INDEX idx_rois_parent   ON rois(parent_roi_id);
CREATE INDEX idx_rois_identity ON rois(cell_identity_id);
```

**Measurement code and export queries filter by `roi_type_id`, never by table name.**

---

## Cell Identity System

`CELL_IDENTITIES` is a stable anchor table. Every physical cell gets one UUID at first segmentation. That UUID persists across all derived FOVs, across merges, across re-analysis.

```sql
CREATE TABLE cell_identities (
    id              BLOB(16) PRIMARY KEY,
    experiment_id   BLOB(16) REFERENCES experiments(id),
    origin_fov_id   BLOB(16) REFERENCES fovs(id),
    origin_label_id INTEGER,
    created_at      TEXT DEFAULT (datetime('now'))
);
```

- **Top-level ROIs (cells):** `cell_identity_id` is always non-NULL
- **Sub-cellular ROIs (particles, P-bodies):** `cell_identity_id` is always NULL — identity is inherited through the `parent_roi_id` join, never stored directly (see S7)
- Cross-FOV measurement queries for cells join on `cell_identity_id`; for particles, join through `parent_roi_id` → cell's `cell_identity_id`

---

## FOV Lineage System

```sql
CREATE TABLE fovs (
    id                BLOB(16) PRIMARY KEY,
    experiment_id     BLOB(16) REFERENCES experiments(id),
    condition_id      BLOB(16) REFERENCES conditions(id),
    bio_rep_id        BLOB(16) REFERENCES bio_reps(id),
    display_name      TEXT NOT NULL,
    auto_name         TEXT NOT NULL,    -- config-driven, e.g. "ctrl_N1_001_msksubt_bgsub"
    fov_index         INTEGER,
    parent_fov_id     BLOB(16) REFERENCES fovs(id),
    derivation_op     TEXT,             -- 'mask_subtract' | 'background_subtract' | 'resegment'
    derivation_params TEXT,             -- JSON: exact params used
    pipeline_run_id   BLOB(16) REFERENCES pipeline_runs(id),
    timepoint_id      BLOB(16) REFERENCES timepoints(id),
    zarr_path         TEXT NOT NULL,
    channel_metadata  TEXT,             -- JSON
    status            TEXT DEFAULT 'imported',
    status_updated_at TEXT,
    updated_at        TEXT,             -- dashboard/debugging, NOT used for merge resolution
    notes             TEXT,
    imported_at       TEXT DEFAULT (datetime('now')),
    CHECK(id != parent_fov_id),                -- prevent self-reference cycles (m3)
    CHECK(derivation_params IS NULL OR json_valid(derivation_params))  -- (m2)
);

CREATE INDEX idx_fovs_parent ON fovs(parent_fov_id) WHERE parent_fov_id IS NOT NULL;
CREATE INDEX idx_fovs_experiment ON fovs(experiment_id);
CREATE INDEX idx_fovs_condition ON fovs(condition_id);
CREATE INDEX idx_fovs_status ON fovs(status);
CREATE UNIQUE INDEX idx_fovs_zarr_path_live ON fovs(zarr_path) WHERE status NOT IN ('deleted');
```

**Status values:** `'pending'` | `'imported'` | `'segmented'` | `'qc_pending'` | `'qc_done'` | `'analyzed'` | `'stale'` | `'deleting'` | `'deleted'` | `'error'`

**Lineage queries use recursive CTE on `parent_fov_id`** — no denormalized `lineage_path` column. Always consistent, performant at expected scale (hundreds of FOVs):

```sql
-- All descendants of a root FOV (with depth guard)
WITH RECURSIVE lineage AS (
    SELECT id, parent_fov_id, auto_name, 0 AS depth
    FROM fovs WHERE id = :root_fov_id
    UNION ALL
    SELECT f.id, f.parent_fov_id, f.auto_name, l.depth + 1
    FROM fovs f JOIN lineage l ON f.parent_fov_id = l.id
    WHERE l.depth < 50  -- MAX_LINEAGE_DEPTH guard
)
SELECT * FROM lineage;

-- All ancestors of a derived FOV (with depth guard)
WITH RECURSIVE ancestors AS (
    SELECT id, parent_fov_id, auto_name, 0 AS depth
    FROM fovs WHERE id = :derived_fov_id
    UNION ALL
    SELECT f.id, f.parent_fov_id, f.auto_name, a.depth + 1
    FROM fovs f JOIN ancestors a ON f.id = a.parent_fov_id
    WHERE a.depth < 50  -- MAX_LINEAGE_DEPTH guard
)
SELECT * FROM ancestors;
```

**Cycle prevention:** `CHECK(id != parent_fov_id)` in schema prevents direct self-reference. Application-level check in `derive_fov()` walks ancestors to prevent deeper cycles.

**Automatic naming** is config-driven via `[derivation_naming]` in TOML:

```toml
[derivation_naming]
mask_subtract       = "msksubt"
background_subtract = "bgsub"
resegment           = "rseg"
separator           = "_"
```

`LayerStore` constructs `auto_name` at derivation time. Never hardcode suffixes in application code.

---

## Assignment System

**`fov_config` is replaced** by `fov_segmentation_assignments` and `fov_mask_assignments`.

### Source of Truth Split

| What | Where |
|---|---|
| Current active assignment | `fov_segmentation_assignments.is_active = 1` |
| How it got assigned | `pipeline_runs` record |
| Link between them | `pipeline_run_id` FK on the assignment row |
| Intent (what config to run) | TOML pipeline topology |

**All three must coexist. Do not collapse them.**

### fov_segmentation_assignments

```sql
CREATE TABLE fov_segmentation_assignments (
    id                  BLOB(16) PRIMARY KEY,
    fov_id              BLOB(16) REFERENCES fovs(id) NOT NULL,
    segmentation_set_id BLOB(16) REFERENCES segmentation_sets(id) NOT NULL,
    roi_type_id         BLOB(16) REFERENCES roi_type_definitions(id) NOT NULL,
    is_active           INTEGER DEFAULT 1,
    assigned_by         TEXT,  -- 'pipeline_run' | 'user_manual' | 'user_copy' | 'merge'
    pipeline_run_id     BLOB(16) REFERENCES pipeline_runs(id),  -- NULL if manual
    assigned_at         TEXT DEFAULT (datetime('now')),
    width               INTEGER,
    height              INTEGER,
    roi_count           INTEGER,
    notes               TEXT
);

CREATE INDEX idx_fsa_fov_active ON fov_segmentation_assignments(fov_id, is_active);
CREATE INDEX idx_fsa_seg_active ON fov_segmentation_assignments(segmentation_set_id, is_active);

-- Enforces at most one active assignment per (fov, roi_type) at the DB level (M8)
-- Deactivate-old and activate-new MUST happen in a single transaction
CREATE UNIQUE INDEX idx_fsa_one_active
ON fov_segmentation_assignments(fov_id, roi_type_id)
WHERE is_active = 1;
```

A single FOV will have **multiple simultaneous active segmentation assignments** — one per ROI type. This is correct and expected.

### Assignment Write Flow

Pipeline runner calls `ExperimentStore`, which delegates to `ExperimentDB` for all SQL operations (including assignments). `PipelineRunner` never writes to assignment tables directly.

```
PipelineRunner.run_step("segment", ...)
  └─► ExperimentStore.run_segmentation(...)
        ├─► LayerStore.write_labels(...)
        ├─► ExperimentDB.insert_segmentation_set(...)
        └─► ExperimentDB.assign_segmentation(
                fov_ids, seg_set_id, roi_type,
                pipeline_run_id=run_id,
                assigned_by='pipeline_run'
            )
```

---

## Two-Layer Internal Architecture

The two layers are **internal to ExperimentStore**. They are not public APIs.

```
CLI / napari widgets
        │
        ▼ (only entry point)
  ExperimentStore  (facade — orchestrates both layers, owns atomicity)
        │
        ├──► ExperimentDB      (ALL SQLite: CRUD, assignments, status, merge)
        └──► LayerStore        (ALL Zarr: images, labels, masks, staging)
```

Assignment logic (segmentation assignments, mask assignments, active-assignment queries, measurement triggers) lives as methods on `ExperimentDB`, not as a separate class. This was changed from the original three-layer design after red team review found that AssignmentService would be ~50-150 lines of pure SQL queries — disproportionate overhead for a separate class.

**Protocol classes** on `ExperimentDB` bound cognitive load on the large class:
- `FOVProtocol` — FOV CRUD, lineage, status
- `SegmentationProtocol` — segmentation sets, ROI extraction
- `MeasurementProtocol` — measurements, bulk insert, active-measurement query
- `ThresholdProtocol` — threshold masks, mask assignments
- `GroupProtocol` — intensity groups, cell group assignments
- `StatusProtocol` — status machine, status log, staleness propagation

These are typing.Protocol classes used for documentation and IDE support, not runtime ABCs.

**Rule:** CLI and napari widgets import `ExperimentStore` only. Never import `ExperimentDB` or `LayerStore` directly from outside the store package.

### Strict Dependency Rules

| Layer | Knows about | Must NOT know about |
|---|---|---|
| `ExperimentDB` | SQL, UUIDs, table names, transactions, assignments | Zarr, numpy arrays, file paths |
| `LayerStore` | Zarr paths, numpy arrays, OME-NGFF | SQL, UUIDs, what an FOV is |
| `ExperimentStore` | Both layers, business rules, atomicity | SQL cursor details, Zarr internals |

If `LayerStore` imports from `ExperimentDB`, the boundary has been violated — push the coordination back up to `ExperimentStore`.

---

## SQLite ↔ Zarr Consistency

Four confirmed mitigations for the dual-store consistency gap:

---

### C1: Staging Path + Atomic Rename (partial Zarr writes)

**Problem:** A crash mid-write leaves a valid directory with incomplete data. Path-existence check blesses it as committed.

**Solution:** Write to staging path, atomic rename to final path on completion.

```python
staging_path = zarr_root / ".pending" / uuid_hex
final_path   = zarr_root / "images"  / uuid_hex

# Write all channels to staging
self._write_channels(staging_path, arrays)

# Atomic rename — only succeeds if all channels written
staging_path.rename(final_path)
```

**Recovery:** On startup, delete entries under `zarr/.pending/` that are older than 5 minutes (concurrent writer safety). Fresh entries may belong to an active writer.

**Constraint:** Staging path must be a sibling on the same volume as the final path, not a subdirectory of it. Rename across mount points or volumes is not atomic. Validate at init time:
```python
assert staging_path.stat().st_dev == final_path.parent.stat().st_dev
```

**Post-rename check:** After `staging_path.rename(final_path)`, verify `final_path.exists()` before committing the DB transaction.

**Recovery validates zarr integrity, not just path existence.** A directory that exists may contain partial data. `validate_zarr_group()` checks for `.zarray` metadata and expected channel count.

---

### S1: Single Transaction for Derived FOV Creation (partial DB writes)

**Problem:** Each sub-step of derived FOV creation commits independently. Crash between steps leaves half-built FOV.

**Solution:** Wrap all four DB steps in one transaction. `queries.py` functions never call `conn.commit()` internally — caller controls commit timing.

```python
# Recommended sequence: Zarr writes OUTSIDE transaction, DB writes inside
# This keeps transactions short for concurrency.

# Step 1: Write Zarr to staging path (outside transaction)
staging = self._zarr.write_to_staging(channels, arrays)

with self._db.transaction():
    # Step 2: DB operations
    fov = self._db.insert_fov(..., status='pending')
    self._db.copy_fov_config(fov.id)
    self._db.duplicate_cells(fov.id)
    self._db.seed_measurements(fov.id)

    # Step 3: Atomic rename staging -> final
    staging.rename(final_path)

    # Step 4: Flip status — a successful commit and imported status are the same event
    self._db.update_fov_status(fov.id, 'imported')
# commit on __exit__, rollback on exception
```

`status='imported'` flip is the final statement inside the transaction. (Note: the earlier version incorrectly used `'committed'` which is not a defined status value. The correct transition is `'pending'` -> `'imported'`.)

---

### S6: Soft-Delete State Machine (orphaned Zarr on DB delete)

**Problem:** CASCADE delete removes DB rows but Zarr directories persist. No reverse-direction cleanup.

**Solution:** Mirror the creation pattern. Hard-delete is never used for entity tables.

```
status='analyzed' (or any live status)  ->  status='deleting'  ->  [delete Zarr]  ->  status='deleted'
```

```python
def delete_fov(self, fov_id: bytes):
    # Step 1: Mark as deleting (survives crash, enables recovery)
    self._db.update_fov_status(fov_id, 'deleting')

    # Step 2: Delete Zarr data
    fov = self._db.get_fov(fov_id)
    self._zarr.delete_path(fov.zarr_path)

    # Step 3: Soft-delete in DB (preserve audit trail and FK integrity)
    self._db.update_fov_status(fov_id, 'deleted')
```

**Recovery:** On startup, retry Zarr deletion for any `status='deleting'` records, then flip to `'deleted'`.

**Why not hard-delete:**
- Audit trail: deleted records still tell the lineage story
- FK integrity: `pipeline_runs` and `measurements` still have valid references
- Merge safety: conflicts between soft-deleted and active records are detectable

**Query discipline:** All "live" FOV queries add `WHERE status NOT IN ('pending', 'deleting', 'deleted', 'error')`.

---

### S8: Concurrent Napari + CLI Access

**Problem:** No busy timeout, no concurrency model. Long pipeline runs block napari writes.

**Solution:**
1. WAL mode + busy_timeout (set on every connection, not once globally)
2. Pipeline runs execute in background thread with their own connection
3. Advisory `.lock` file during startup recovery only

```python
def _configure_connection(self, conn: sqlite3.Connection):
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")  # 30s before raising OperationalError
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row

# Background pipeline runner gets its own connection
def run_pipeline_async(self, pipeline_name: str, fov_ids: list[bytes]):
    def _run():
        conn = sqlite3.connect(self._db_path)
        self._configure_connection(conn)
        runner = PipelineRunner(conn, self._zarr, self._config)
        runner.run(pipeline_name, fov_ids)
        conn.close()
    threading.Thread(target=_run, daemon=True).start()
```

Advisory lock file pattern (recovery only, with atomic creation):

```python
def _run_recovery(self):
    lock_path = self._path / ".recovery.lock"
    try:
        # Atomic lock creation — no TOCTOU race
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError:
        # Check for stale lock (older than 5 minutes)
        if lock_path.stat().st_mtime < time.time() - 300:
            lock_path.unlink(missing_ok=True)
            return self._run_recovery()  # Retry once
        return   # another process is recovering
    try:
        self._recover_pending_zarr()
        self._recover_pending_fovs()
        self._recover_deleting_fovs()
    finally:
        lock_path.unlink(missing_ok=True)
```

---

## Full Recovery Procedure (Startup)

Recovery must log every action and print a summary. Never silently delete data.

```python
def _startup_recovery(self):
    actions = []

    # 1. Zarr staging cleanup — only entries older than threshold (concurrent writer safety)
    age_threshold = time.time() - 300  # 5 minutes
    for path in (self._zarr_root / ".pending").iterdir():
        if path.stat().st_mtime < age_threshold:
            shutil.rmtree(path, ignore_errors=True)
            actions.append(f"Cleaned stale staging dir: {path.name}")

    # 2. Pending DB records — validate Zarr integrity, not just path existence
    for fov in self._db.get_fovs_by_status('pending'):
        if self._zarr.validate_zarr_group(fov.zarr_path):
            self._db.update_fov_status(fov.id, 'imported')
            actions.append(f"Promoted pending FOV: {fov.display_name}")
        else:
            self._db.update_fov_status(fov.id, 'error',
                                        message='Incomplete write recovered on startup')
            actions.append(f"Marked as error (incomplete): {fov.display_name}")

    # 3. Deleting records — retry Zarr deletion
    for fov in self._db.get_fovs_by_status('deleting'):
        try:
            self._zarr.delete_path(fov.zarr_path)
            self._db.update_fov_status(fov.id, 'deleted')
            actions.append(f"Completed deletion: {fov.display_name}")
        except Exception as e:
            self._db.update_fov_status(fov.id, 'error', message=str(e))
            actions.append(f"Deletion failed: {fov.display_name} ({e})")

    # 4. Log and summarize
    if actions:
        self._write_recovery_log(actions)
        self._print_recovery_summary(actions)
```

---

## Configuration System

**TOML + Pydantic v2.**

- TOML is Python stdlib (3.11+), human-readable, version-controllable
- Pydantic validates on load, provides IDE autocompletion everywhere
- `experiment.toml` lives alongside `experiment.percell/` — shareable, git-trackable

**Config structure (two distinct sections):**
- `[op_configs.*]` — how each operation runs (parameters, channels, preprocessing)
- `[[pipelines]]` — what operations run and in what order (topology)

**`output_tag`** in pipeline steps is a logical name resolved to a DB entity ID by `PipelineRunner` at execution time. Never embed UUIDs in TOML.

---

## Refactor Sequence from percell3

Execute in order. Each phase leaves the public API working before the next begins.

1. **Extract `LayerStore`** — move all Zarr/OME-NGFF code. `ExperimentStore` holds an instance, calls it. Test: existing CLI commands pass.
2. **Extract `ExperimentDB`** — move all `sqlite3` cursor/connection code, including assignment logic (formerly planned as a separate AssignmentService). Test: existing CLI commands pass.
3. **Schema additions** — `cell_identities`, `roi_type_definitions`, assignment tables, status machine. DB layer is clean, so additions are surgical.
4. **Migrate `fov_config`** — translate existing rows to `fov_segmentation_assignments` and `fov_mask_assignments` with `assigned_by='migrated_from_fov_config'`.

---

## ID Migration Strategy (C2)

**Use type aliases, not newtype wrappers.**

```python
# db_types.py — document intent, costs nothing to adopt
import uuid

FovId             = bytes
RoiId             = bytes
SegmentationSetId = bytes
CellIdentityId    = bytes
ExperimentId      = bytes
ConditionId       = bytes

def new_uuid() -> bytes:
    return uuid.uuid4().bytes

def uuid_to_str(b: bytes) -> str:
    return str(uuid.UUID(bytes=b))

def str_to_uuid(s: str) -> bytes:
    return uuid.UUID(s).bytes
```

Aliases document intent, cost nothing to adopt, and avoid compounding the 760+ call site migration with wrapper class overhead. Name all UUID variables explicitly in function signatures — never `id1: bytes, id2: bytes`.

Migration is a scripted AST-transform problem, not a type-system problem.

---

## Kill Criteria and Gate Sequence (C3)

percell3 on `main` is the natural rollback. Do not merge percell4 to main until Gate 3 passes.

### Gate Sequence (16-20 weeks)

**Gate 0 — Schema + DB + Config (week 4):**
A lab member can run `percell4 create` and `percell4 status`. Config loading, DB schema (ExperimentDB with all CRUD and assignment methods), and status system work end to end. No measurement engine, no segmentation, no Zarr writes, no import.

*Kill criterion:* If Gate 0 takes more than 4 weeks of active development, stop and diagnose. The schema and config system should be the easiest part.

**Gate 1 — Single FOV round-trip + legacy import + export-compat (week 8):**
Import a TIFF, write to Zarr, record in DB, read it back, display in napari. LayerStore and ExperimentStore facade working. `percell4 import-legacy` reads percell3 Zarr images. `percell4 export-compat` produces percell3-compatible CSV. Validates that `ExperimentDB` and `LayerStore` are correctly separated and Zarr consistency mitigations (C1, S1, S6) actually work.

*Kill criterion:* If the DB/Zarr split produces more coordination complexity than the monolith it replaced, reconsider the split. Test: is `ExperimentDB` simpler than the DB portion of the old `ExperimentStore`? If no, the extraction is wrong.

**Gate 2 — Measurement + segmentation + plugins (week 14):**
Segmentation module works. A lab member can run Cellpose on a real FOV, QC it in napari, and the result is stored with correct `cell_identity_id` linkage. All plugins ported.

*Kill criterion:* If cell identity linkage or the ROI type system requires significant schema revision to work in practice, stop and redesign before porting more modules.

**Gate 3 — CLI + interactive menu + workflows + user validation (week 20):**
A lab member (not the developer) runs their actual P-body workflow start to finish using percell4. Real experimental data, real conditions, real export. They complete the workflow without asking for help on mechanics. The interactive menu system is fully ported. All workflows operational.

*Kill criterion:* If the user cannot complete the workflow independently, the UI/UX is wrong regardless of the schema. Stop and fix before adding features.

### Hard Kill Criteria (evaluate at any point)

- **Timeline:** Not at Gate 2 within 14 weeks of active coding time -> stop and assess.
- **Data loss:** Any real `.percell` file corrupted by a percell4 bug -> zero tolerance, stop immediately.
- **percell3 regression:** If percell3 on main stops being usable for lab work during percell4 development -> refactor has become a liability.
- **Growing complexity:** Two-layer split producing more code than the monolith without visible benefit -> architecture is wrong.

### Reverse Migration Path

percell4 `.percell` files are a superset of percell3 in schema terms. `percell4 export-compat` (Gate 1 requirement) writes a percell3-compatible CSV export of cell measurements. No researcher ever loses data due to a percell4 rollback.

---

## Merge Strategy (S2)

**`INSERT OR IGNORE` — append-only, no last-writer-wins.**

**Design rule:** Re-run = new pipeline run = new UUIDs. A researcher who re-analyzed data on their local copy should re-run before merging, which produces new UUIDs that merge cleanly alongside the original run. Both runs coexist in the merged database, queryable by `pipeline_run_id`. The active/latest run is determined by the assignment system and `status` fields, not by which row won a merge conflict.

Last-writer-wins is wrong for science — silently overwriting a measurement result because someone's laptop clock was ahead is a data integrity failure that doesn't surface until a paper is being reviewed.

**Pre-merge conflict check** raises `MergeConflictError` if the same UUID exists with different content. The check covers ALL entity tables, not just measurements and rois:

```python
def merge_experiment(source_path: str, target_db: Connection):
    # Use parameter binding — never f-string for ATTACH (SQL injection via filenames)
    target_db.execute("ATTACH ? AS source", (source_path,))

    # Schema version check
    source_version = target_db.execute(
        "SELECT schema_version FROM source.experiments LIMIT 1"
    ).fetchone()
    target_version = target_db.execute(
        "SELECT schema_version FROM experiments LIMIT 1"
    ).fetchone()
    if source_version != target_version:
        raise MergeConflictError("Schema version mismatch")

    # Pre-merge check: find UUIDs that exist in both with different content
    # Covers ALL entity tables, not just measurements and rois
    conflicts = target_db.execute("""
        SELECT 'measurements' AS tbl, uuid_str(s.id) AS id_hex
        FROM source.measurements s
        JOIN measurements t ON t.id = s.id
        WHERE s.value != t.value OR s.metric != t.metric

        UNION ALL

        SELECT 'rois', uuid_str(s.id)
        FROM source.rois s
        JOIN rois t ON t.id = s.id
        WHERE s.fov_id != t.fov_id

        UNION ALL

        SELECT 'fovs', uuid_str(s.id)
        FROM source.fovs s
        JOIN fovs t ON t.id = s.id
        WHERE s.zarr_path != t.zarr_path OR s.status != t.status

        UNION ALL

        SELECT 'segmentation_sets', uuid_str(s.id)
        FROM source.segmentation_sets s
        JOIN segmentation_sets t ON t.id = s.id
        WHERE s.parameters != t.parameters
    """).fetchall()

    if conflicts:
        raise MergeConflictError(
            f"{len(conflicts)} conflicting rows detected. "
            f"Re-run the analysis on the source file to generate new UUIDs "
            f"before merging."
        )

    # Disable FK checks during merge (self-referential FKs make ordering impossible)
    target_db.execute("PRAGMA foreign_keys=OFF")

    # Insert in topological order (MERGE_TABLE_ORDER constant)
    # Exclude non-committed FOVs from source
    for table in MERGE_TABLE_ORDER:
        assert table.isidentifier()  # Guard against injection
        if table == 'fovs':
            target_db.execute(
                f"INSERT OR IGNORE INTO {table} SELECT * FROM source.{table} "
                f"WHERE status NOT IN ('pending', 'deleting', 'deleted', 'error')"
            )
        elif table == 'fov_status_log':
            # INTEGER PK collides — use temp table + UNION ALL approach
            target_db.execute(f"""
                INSERT INTO {table} (fov_id, old_status, new_status, message, created_at)
                SELECT s.fov_id, s.old_status, s.new_status, s.message, s.created_at
                FROM source.{table} s
                LEFT JOIN {table} t ON t.fov_id = s.fov_id
                    AND t.new_status = s.new_status AND t.created_at = s.created_at
                WHERE t.id IS NULL
            """)
        else:
            target_db.execute(
                f"INSERT OR IGNORE INTO {table} SELECT * FROM source.{table}"
            )

    # Post-merge validation
    fk_errors = target_db.execute("PRAGMA foreign_key_check").fetchall()
    if fk_errors:
        raise MergeConflictError(f"FK integrity violation: {len(fk_errors)} errors")

    # Cycle detection
    cycles = target_db.execute("""
        WITH RECURSIVE cycle_check AS (
            SELECT id, parent_fov_id, 1 AS depth
            FROM fovs WHERE parent_fov_id IS NOT NULL
            UNION ALL
            SELECT c.id, f.parent_fov_id, c.depth + 1
            FROM cycle_check c JOIN fovs f ON c.parent_fov_id = f.id
            WHERE c.depth < 50
        )
        SELECT uuid_str(id) FROM cycle_check WHERE parent_fov_id = id
    """).fetchall()
    if cycles:
        raise MergeConflictError(f"FOV lineage cycle detected: {cycles}")

    # zarr_path uniqueness check (non-deleted FOVs only)
    dupes = target_db.execute("""
        SELECT zarr_path, COUNT(*) FROM fovs
        WHERE status NOT IN ('deleted')
        GROUP BY zarr_path HAVING COUNT(*) > 1
    """).fetchall()
    if dupes:
        raise MergeConflictError(f"Duplicate zarr_path detected: {dupes}")

    # Handle assignment conflicts (duplicate active for same fov+roi_type)
    # Deactivate source assignments that conflict with target
    target_db.execute("""
        UPDATE fov_segmentation_assignments SET is_active = 0
        WHERE id IN (
            SELECT s.id FROM source.fov_segmentation_assignments s
            JOIN fov_segmentation_assignments t
                ON s.fov_id = t.fov_id AND s.roi_type_id = t.roi_type_id
            WHERE s.is_active = 1 AND t.is_active = 1 AND s.id != t.id
        )
    """)

    # Re-enable FK checks
    target_db.execute("PRAGMA foreign_keys=ON")

    target_db.execute("DETACH source")
```

**Note on deletions and merge:** Merge is append-only. Deletions do not propagate across databases. If data was soft-deleted in the target and the source contains the same data, it will be re-inserted (resurrection). This is a documented known limitation. Consider tombstones in a future version if this becomes a practical problem.

Add `updated_at` columns to entity tables for dashboard/debugging use ("last analyzed 3 days ago"). Do not use them for merge resolution.

---

## Cell Identity Integrity (S7)

Three mitigations:

### 1. Unique index: one ROI per identity per FOV

```sql
CREATE UNIQUE INDEX idx_roi_identity_fov
ON rois(cell_identity_id, fov_id)
WHERE cell_identity_id IS NOT NULL;
```

Enforced in schema. A cell can only appear once in any given image.

### 2. cell_identity_id NULL rules

- **Top-level ROIs (cells):** `cell_identity_id` is always non-NULL.
- **Sub-cellular ROIs (particles, P-bodies):** `cell_identity_id` is always NULL. Identity is inherited through the `parent_roi_id` join, never stored directly.

Enforced in the application write path, not the schema (the conditional can't be expressed as a CHECK constraint without a join):

```python
def insert_roi(self, roi_type_id: bytes, cell_identity_id: bytes | None, ...):
    type_def = self._db.get_roi_type_definition(roi_type_id)

    if type_def.parent_type_id is None and cell_identity_id is None:
        raise ValueError("Top-level ROI types (cells) must have a cell_identity_id")

    if type_def.parent_type_id is not None and cell_identity_id is not None:
        raise ValueError("Sub-cellular ROI types (particles) must not have cell_identity_id — "
                        "identity is inherited through parent_roi_id")
```

### 3. Spatial overlap validation (audit, not write guard)

Runs as a post-segmentation audit step. Returns warnings surfaced in napari Cell Inspector. Does not block writes — manual redraw of a corrected cell is a legitimate operation that would fail a hard block.

```python
def validate_identity_linkage(self, fov_id: bytes) -> list[IdentityWarning]:
    """
    Checks that ROIs sharing a cell_identity_id across FOVs in the same
    lineage have plausible spatial overlap. Returns warnings, does not block.
    Run after segmentation and after manual edits.
    """
```

---

## Maintenance and Sunset (S4)

percell3 status during percell4 development: **critical bug fixes only.**

| Critical (fix in percell3) | Not critical (percell4 only) |
|---|---|
| Data corruption | UI annoyances |
| Measurement calculation errors | Missing features |
| Crash on valid input | Export formatting issues |
| Any bug causing wrong numbers | Workflow inconveniences |

**Freeze trigger:** Gate 3 passes (lab member completes P-body workflow independently in percell4). From that point, the answer to any percell3 bug report is "this is fixed in percell4, migrate your experiment."

Set the freeze date in advance, not reactively. Add to percell3 README:

> **Maintenance status:** Critical bug fixes only. percell3 will be frozen
> when percell4 reaches Gate 3 (full user workflow validation).
> New features and non-critical fixes are percell4 only.

---

## V1 TOML Scope (S10)

**Python 3.11+ required** for `tomllib` stdlib and `StrEnum`.

V1 config loader parses `[[roi_types]]` and `[op_configs]` only. `[[pipelines]]` section is explicitly rejected with a clear error message.

**TOML creation tooling:** `percell4 init` (or interactive `percell4 create`) generates a default `experiment.toml` by asking questions: "Experiment name? How many channels? Channel names?" Include a `--template` flag that writes a commented example TOML. This is the difference between adoption and abandonment.

### V1 experiment.toml example

```toml
[experiment]
name = "P-body Two-Channel Sensor"

[[channels]]
name  = "sensor_ch1"
role  = "signal"
color = "green"

[[channels]]
name  = "sensor_ch2"
role  = "signal"
color = "red"

[[roi_types]]
name         = "cell"
display_name = "Cells"
color        = "#4A90D9"

[[roi_types]]
name         = "pbody"
display_name = "P-bodies"
parent_type  = "cell"
color        = "#E8A838"

[op_configs.cellpose_initial]
method   = "cellpose"
channel  = "sensor_ch1"
model    = "cyto3"
diameter = 30.0

# [[pipelines]] — deferred to v2
```

### Pydantic model

```python
class ExperimentConfigV1(BaseModel):
    experiment: ExperimentMeta
    channels: list[ChannelConfig]
    roi_types: list[RoiTypeConfig]
    op_configs: dict[str, dict]   # permissive dict for now — validate per-op in v2

    pipelines: None = Field(None, exclude=True)

    @classmethod
    def from_toml(cls, path: str) -> "ExperimentConfigV1":
        with open(path, "rb") as f:
            data = tomllib.load(f)
        if "pipelines" in data:
            raise ConfigError(
                "[[pipelines]] is not supported in v1. "
                "Remove the pipelines section or upgrade to v2."
            )
        return cls(**data)
```

### How it connects

- **ROI type creation:** `ExperimentStore.initialize()` calls `ExperimentConfigV1.from_toml()`, populates `roi_type_definitions` from `[[roi_types]]`. TOML is required to create an experiment.
- **`pipeline_run_id` on assignments:** All v1 operations (segmentation, threshold, measure) create `pipeline_runs` records. Pipeline runner being deferred means no TOML-driven multi-step automation, not that provenance stops being written.
- **`assigned_by` values:** `'pipeline_run'` | `'user_manual'` | `'user_copy'` | `'merge'`. No `'cli_interactive'` — CLI operations always go through `pipeline_runs`.

---

## Assignment Measurement Trigger (M3)

Assignment methods on `ExperimentDB` stay pure (no Zarr knowledge). The measurement trigger is explicit via return values, not a hidden side effect.

```python
@dataclass
class MeasurementNeeded:
    fov_id: bytes
    segmentation_set_id: bytes
    roi_type_id: bytes
    reason: str   # 'new_assignment' | 'reassignment'

# ExperimentDB.assign_segmentation() returns list[MeasurementNeeded]
# ExperimentStore consumes the list and dispatches to MeasurementEngine
```

Flow: `ExperimentStore.run_segmentation()` -> calls `ExperimentDB.assign_segmentation()` -> gets back `list[MeasurementNeeded]` -> invokes measurer for each. Coordination lives in the facade, not buried in the DB layer.

---

## Measurement Scope Enum (M5)

Rename `'whole_cell'` -> `'whole_roi'` in schema and internal code. With unified ROIs, `whole_cell` is semantically wrong for particles.

**Internal/schema scope values:** `'whole_roi'` | `'mask_inside'` | `'mask_outside'`

**User-facing contexts (CLI, CSV export, menu) keep `whole_cell`** to avoid breaking researcher vocabulary and downstream R/Prism scripts:

```python
# Display scope names for researcher-facing output
SCOPE_DISPLAY = {
    'whole_roi': 'whole_cell',
    'mask_inside': 'mask_inside',
    'mask_outside': 'mask_outside',
}
```

---

## Measurements Table (M6)

```sql
CREATE TABLE measurements (
    id              BLOB(16) PRIMARY KEY,
    roi_id          BLOB(16) REFERENCES rois(id) NOT NULL,
    channel_id      BLOB(16) REFERENCES channels(id) NOT NULL,
    metric          TEXT NOT NULL,     -- 'mean' | 'max' | 'min' | 'integrated' | 'std' | 'median' | 'area'
    value           REAL NOT NULL,
    scope           TEXT NOT NULL,     -- 'whole_roi' | 'mask_inside' | 'mask_outside'
    pipeline_run_id BLOB(16) REFERENCES pipeline_runs(id),
    updated_at      TEXT,
    CHECK(scope IN ('whole_roi', 'mask_inside', 'mask_outside'))
);

CREATE INDEX idx_measurements_roi     ON measurements(roi_id);
CREATE INDEX idx_measurements_channel ON measurements(channel_id);
CREATE INDEX idx_measurements_run     ON measurements(pipeline_run_id);
CREATE INDEX idx_measurements_roi_channel_scope ON measurements(roi_id, channel_id, scope);
CREATE UNIQUE INDEX idx_measurements_unique_per_run
ON measurements(roi_id, channel_id, metric, scope, pipeline_run_id);
```

`pipeline_run_id` enables "delete everything from failed run X" without scanning. Long/narrow format only — never wide.

---

## FOV Status Transition Enforcement (M7)

Valid transitions enforced in application code. Status column update and log write happen in the same transaction.

```python
VALID_TRANSITIONS = {
    'pending':    {'imported', 'error'},
    'imported':   {'segmented', 'error', 'deleting'},
    'segmented':  {'qc_pending', 'error', 'deleting'},
    'qc_pending': {'qc_done', 'segmented', 'error'},
    'qc_done':    {'analyzed', 'error', 'deleting'},
    'analyzed':   {'stale', 'deleting'},
    'stale':      {'analyzed', 'deleting'},
    'deleting':   {'deleted', 'error'},
    'error':      {'imported', 'deleting'},  # retry allowed
    'deleted':    set(),                      # terminal
}

def update_fov_status(self, fov_id: bytes, new_status: str, message: str = ''):
    fov = self._db.get_fov(fov_id)
    current = fov.status
    if new_status not in VALID_TRANSITIONS[current]:
        raise InvalidStatusTransition(
            f"FOV '{fov.display_name}' cannot move from {current} to {new_status}. "
            f"(id: {uuid_to_str(fov_id)})"
        )
    with self._db.transaction():
        self._db.set_fov_status(fov_id, new_status)
        self._db.insert_status_log(fov_id, new_status, message)
    # Propagate staleness to descendants if data changed
    if new_status in ('segmented', 'analyzed', 'imported'):
        self._db.mark_descendants_stale(fov_id)
```

---

## Cell Group Assignments Merge Safety (M9)

Add `pipeline_run_id` as discriminator. Multiple grouping runs coexist per ROI.

```sql
CREATE TABLE cell_group_assignments (
    roi_id             BLOB(16) REFERENCES rois(id),
    intensity_group_id BLOB(16) REFERENCES intensity_groups(id),
    pipeline_run_id    BLOB(16) REFERENCES pipeline_runs(id),
    grouping_value     REAL,
    assigned_at        TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (roi_id, intensity_group_id, pipeline_run_id)
);
```

Same ROI can have different group assignments from different pipeline runs, both preserved during merge.

---

## CLI Rewrite Strategy (M4)

Port menu handlers one at a time with integration tests. No big-bang rewrite of 5,372 lines.

- Each handler is considered ported only when it has an integration test running against real (small) data
- Test against the new `ExperimentStore` API, not mocks
- Port in dependency order: create -> init -> import -> import-legacy -> status -> segment -> measure -> threshold -> export -> export-compat -> export-prism
- **The interactive menu system (5,372 lines) is a Gate 3 requirement.** Port menu categories in dependency order matching CLI handlers. A researcher cannot complete the P-body workflow "independently" using Click subcommands they have never seen before.
- **`percell4 import-legacy`** reads percell3 Zarr images and creates a fresh percell4 experiment. Gate 1 requirement.
- **`percell4 export-compat`** produces percell3-compatible CSV export. Gate 1 requirement.
- **`percell4 export-prism`** for GraphPad Prism formatted output.
- **`percell4 init`** generates default `experiment.toml` interactively.

---

## Test Strategy (M11)

- percell3's 1,363 tests are **not** ported — they test percell3 behavior
- percell4 tests are written fresh for percell4 behavior
- Any extracted layer (`ExperimentDB`, `LayerStore`) requires unit tests before the extraction is considered complete
- Integration tests run against real (small) `.percell` files, not mocks
- Minimum passing count before Gate 1: all unit tests for `ExperimentDB` (including assignment methods) and `LayerStore`, plus the round-trip integration test
- Each ported CLI handler requires an integration test (M4)
- Each ported interactive menu category requires an integration test

---

## UUIDv7 Note (m1)

`new_uuid()` currently uses `uuid.uuid4()`. Consider switching to UUIDv7 (time-ordered) before first production data is written — better B-tree insert locality for BLOB(16) indexes. This is a one-line change in `db_types.py` since all call sites use the `new_uuid()` helper. Defer decision until benchmarking at Gate 1.

---

## Resolved Schema Gaps (from specflow analysis)

### Segmentation Sets

One Cellpose run across N FOVs. Per-FOV stats live on the assignment junction table, not the set.

```sql
CREATE TABLE segmentation_sets (
    id                   BLOB(16) PRIMARY KEY,
    experiment_id        BLOB(16) REFERENCES experiments(id),
    produces_roi_type_id BLOB(16) REFERENCES roi_type_definitions(id),
    name                 TEXT,           -- human label, e.g. "cyto3 round 1 ctrl"
    seg_type             TEXT,           -- 'cellpose' | 'manual' | 'threshold_based'
    op_config_name       TEXT,           -- references [op_configs.*] key in TOML
    source_channel       TEXT,
    model_name           TEXT,
    parameters           TEXT,           -- JSON: diameter, flow_threshold, etc.
    fov_count            INTEGER DEFAULT 0,
    total_roi_count      INTEGER DEFAULT 0,
    pipeline_run_id      BLOB(16) REFERENCES pipeline_runs(id),
    created_at           TEXT DEFAULT (datetime('now'))
);
```

Per-FOV columns (`width`, `height`, `roi_count`) are now included directly in the `fov_segmentation_assignments` DDL above.

Relationship: `segmentation_sets 1 ---- N fov_segmentation_assignments N ---- 1 fovs`

### Threshold Masks and Mask Assignments

Binary masks are separate from ROI-producing segmentations. Masks are spatial filters for measurement scoping. Particle ROIs produced by thresholding go through `fov_segmentation_assignments` with `seg_type='threshold_based'`.

```sql
CREATE TABLE threshold_masks (
    id                  BLOB(16) PRIMARY KEY,
    experiment_id       BLOB(16) REFERENCES experiments(id),
    fov_id              BLOB(16) REFERENCES fovs(id),
    pipeline_run_id     BLOB(16) REFERENCES pipeline_runs(id),
    source_channel      TEXT,
    grouping_channel    TEXT,
    method              TEXT,       -- 'otsu' | 'manual' | 'percentile'
    op_config_name      TEXT,
    threshold_value     REAL,
    histogram           TEXT,       -- JSON: for Group Manager widget display
    dilation_px         INTEGER DEFAULT 0,
    zarr_path           TEXT NOT NULL,
    status              TEXT DEFAULT 'pending',
    created_at          TEXT DEFAULT (datetime('now'))
);

CREATE TABLE fov_mask_assignments (
    id                  BLOB(16) PRIMARY KEY,
    fov_id              BLOB(16) REFERENCES fovs(id),
    threshold_mask_id   BLOB(16) REFERENCES threshold_masks(id),
    purpose             TEXT,    -- 'measurement_scope' | 'background_estimation' | 'fov_derivation'
    is_active           INTEGER DEFAULT 1,
    assigned_by         TEXT,
    pipeline_run_id     BLOB(16) REFERENCES pipeline_runs(id),
    assigned_at         TEXT DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX idx_fma_one_active
ON fov_mask_assignments(fov_id, threshold_mask_id, purpose)
WHERE is_active = 1;
```

**Threshold workflow mapping:**
```
threshold operation
    │
    ├──► threshold_masks record      (the binary image + metadata)
    │    + zarr write of binary mask
    │    + fov_mask_assignments record (purpose='measurement_scope')
    │
    └──► if dilation + particle analysis follows:
         segmentation_sets record    (seg_type='threshold_based')
         + rois records              (the connected components as ROIs)
         + fov_segmentation_assignments record (produces_roi_type_id=pbody)
```

`fov_segmentation_assignments` owns all ROI-producing operations. `fov_mask_assignments` owns binary masks used as spatial filters. Different concepts, different tables.

### Pipeline Runs

Per-operation granularity. One record per Cellpose run, threshold operation, or BG subtraction.

```sql
CREATE TABLE pipeline_runs (
    id              BLOB(16) PRIMARY KEY,
    experiment_id   BLOB(16) REFERENCES experiments(id),
    operation_name  TEXT NOT NULL,     -- 'cellpose_segment' | 'otsu_threshold' | 'mask_subtract' | ...
    config_snapshot TEXT,              -- JSON: full parameters used
    status          TEXT DEFAULT 'running',  -- 'running' | 'completed' | 'failed' | 'cancelled'
    started_at      TEXT DEFAULT (datetime('now')),
    completed_at    TEXT,
    error_message   TEXT
);
```

### FOV Status Log

Integer PK (append-only log table).

```sql
CREATE TABLE fov_status_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fov_id      BLOB(16) REFERENCES fovs(id),
    old_status  TEXT,
    new_status  TEXT NOT NULL,
    message     TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_fov_status_log_fov ON fov_status_log(fov_id);
```

### Timepoints

Kept with UUID PK. FK from fovs.

```sql
CREATE TABLE timepoints (
    id            BLOB(16) PRIMARY KEY,
    experiment_id BLOB(16) REFERENCES experiments(id),
    name          TEXT NOT NULL,
    time_seconds  REAL,
    display_order INTEGER
);
```

Add to fovs: `timepoint_id BLOB(16) REFERENCES timepoints(id)` (nullable).

### Experiments

```sql
CREATE TABLE experiments (
    id              BLOB(16) PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT,
    schema_version  TEXT NOT NULL DEFAULT '5.0.0',
    config_hash     TEXT,        -- hash of experiment.toml for change detection
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT
);
```

### Conditions and Bio Reps

```sql
CREATE TABLE conditions (
    id            BLOB(16) PRIMARY KEY,
    experiment_id BLOB(16) REFERENCES experiments(id),
    name          TEXT NOT NULL,
    description   TEXT,
    UNIQUE(experiment_id, name)
);

CREATE TABLE bio_reps (
    id            BLOB(16) PRIMARY KEY,
    experiment_id BLOB(16) REFERENCES experiments(id),
    name          TEXT NOT NULL,
    UNIQUE(experiment_id, name)
);
```

### Channels

```sql
CREATE TABLE channels (
    id              BLOB(16) PRIMARY KEY,
    experiment_id   BLOB(16) REFERENCES experiments(id),
    name            TEXT NOT NULL,
    role            TEXT,           -- 'signal' | 'reference' | 'segmentation'
    excitation_nm   REAL,
    emission_nm     REAL,
    color           TEXT,
    is_segmentation INTEGER DEFAULT 0,
    display_order   INTEGER,
    UNIQUE(experiment_id, name)
);
```

### Intensity Groups

```sql
CREATE TABLE intensity_groups (
    id              BLOB(16) PRIMARY KEY,
    experiment_id   BLOB(16) REFERENCES experiments(id),
    name            TEXT NOT NULL,
    channel_id      BLOB(16) REFERENCES channels(id),
    threshold_value REAL,
    is_excluded     INTEGER DEFAULT 0,
    pipeline_run_id BLOB(16) REFERENCES pipeline_runs(id),
    created_at      TEXT DEFAULT (datetime('now'))
);
```

### ROI Columns Decision

The `rois` table stays lean — geometry only (bbox, area_px, label_id, polygon). All morphometrics (centroid, perimeter, circularity, eccentricity, solidity, axis lengths) and per-particle intensity values are stored as rows in the `measurements` table with appropriate `metric` names. This keeps one code path for all measurement queries regardless of ROI type.

### Tags — Deferred to V2

Tagging system (tags, cell_tags, fov_tags) dropped from v1. Intensity groups handle the primary grouping use case. General tagging deferred.

### lab_members — Deferred

Multi-user provenance via `lab_members` table deferred. Not needed for v1 where 3-6 researchers work on separate files.
