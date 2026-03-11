# Answer: UUID vs Integer ID Strategy for PerCell4

## Clarification: This Is Not a Single-User Desktop App

This is **lab-shared analysis software** used by a team of 3-6 researchers. Each researcher runs their own local `.percell` experiment files, but those files are designed to be **merged, shared, and pooled** for combined analysis. This changes the ID strategy fundamentally.

---

## Direct Answer: Use UUIDs Stored as BLOB(16)

**Do not use plain integer IDs as primary keys.** The hybrid approach (integer PKs + a separate `stable_identity` column) adds complexity without solving the core problem cleanly. Use UUIDs throughout, stored efficiently as `BLOB(16)`.

---

## Why Integer IDs Fail Here

### 1. Database Merging Is a First-Class Feature

Researchers will complete experiments on their own machines and merge `.percell` files to pool data for combined analysis. With integer PKs, `cell_identity_id = 47` exists in *every* `.percell` file ever created. Merging requires:
- Reading all IDs from source
- Detecting collisions with target
- Remapping every foreign key in every table
- Maintaining a translation table during the merge
- Risk of silent corruption if any step is missed

With UUID PKs, merging is a straight `INSERT OR IGNORE`:

```python
def merge_experiment(source_path: str, target_db: Connection):
    target_db.execute(f"ATTACH '{source_path}' AS source")
    target_db.execute("INSERT OR IGNORE INTO cell_identities SELECT * FROM source.cell_identities")
    target_db.execute("INSERT OR IGNORE INTO rois SELECT * FROM source.rois")
    # ... repeat for all tables
    target_db.execute("DETACH source")
```

`INSERT OR IGNORE` is idempotent — merging the same file twice produces no duplicates.

### 2. ML Training Data Requires Globally Stable IDs

A planned feature is exporting image/label pairs for training ML models for particle identification. Each training sample needs an ID that is:
- Permanently stable
- Globally unique across all `.percell` files, all machines, all time
- Traceable back to its source cell, FOV, and experiment after a merge

Integer IDs cannot provide this. `particle_id = 1203` from one file is meaningless next to `particle_id = 1203` from another file. A UUID-identified particle is the same particle forever, regardless of which database it lives in.

### 3. Multi-User Provenance

Merged data must retain who ran what. Every entity (experiment, pipeline run, segmentation set, measurement run) carries a `created_by` reference to a `lab_members` table. This provenance must survive merges intact, which again requires globally unique IDs.

---

## Why the Hybrid Approach (Integer PK + stable_identity) Is Worse

The hybrid would look like:

```sql
CREATE TABLE cell_identities (
    id            INTEGER PRIMARY KEY,   -- local, fast
    stable_id     TEXT UNIQUE            -- UUID for cross-file identity
);
```

This sounds like a compromise but creates two problems:

1. **Every foreign key still uses the integer.** So every merge still requires full ID remapping of all foreign keys — the hard problem is unsolved.
2. **Two ID systems to reason about everywhere.** Every query, every export, every debug session requires knowing which ID to use and when. This is ongoing cognitive overhead for every developer and every future contributor.

The hybrid solves nothing and adds confusion. Pick one system and commit to it.

---

## Why BLOB(16) Recovers the Performance Cost

The standard objection to UUIDs in SQLite is that storing them as 36-character TEXT strings (`'a3f2c1d0-4e5b-...'`) is slow and bloated. This is true. The solution is to store raw UUID bytes as `BLOB(16)`:

- `BLOB(16)` = 16 bytes, same size as two 64-bit integers
- Index performance is equivalent to integer PKs at this size
- Joins across millions of measurement rows remain fast

```python
import uuid

# Generate
new_id = uuid.uuid4()

# Store as bytes
cursor.execute("INSERT INTO cell_identities (id) VALUES (?)", (new_id.bytes,))

# Retrieve and reconstruct
row = cursor.fetchone()
cell_id = uuid.UUID(bytes=row['id'])

# Helper functions — use these everywhere
def new_uuid() -> bytes:
    return uuid.uuid4().bytes

def uuid_to_str(b: bytes) -> str:
    return str(uuid.UUID(bytes=b))

def str_to_uuid(s: str) -> bytes:
    return uuid.UUID(s).bytes
```

Wrap these in a `db_utils.py` module so UUID handling is never written ad hoc.

---

## The One Place Integers Are Fine

Use `INTEGER` (SQLite rowid) for:
- Log tables where you only ever append and query by time (`fov_status_log`, `pipeline_run_log`)
- Junction/mapping tables where the row itself has no external identity (`cell_group_assignments`, `group_members`)
- Any table that is never referenced by external systems and never merged

Use `BLOB(16)` UUID for:
- Every entity table that a researcher or external system might reference by ID (`experiments`, `fovs`, `cell_identities`, `rois`, `segmentation_sets`, `threshold_masks`, `measurements`, `pipeline_runs`, `lab_members`)

---

## Summary Decision

| Scenario | ID Strategy |
|---|---|
| Single-user, never merged | Integer PKs are fine |
| Multi-user, files merged across machines | UUID BLOB(16) required |
| ML training data export | UUID BLOB(16) required |
| Lab team with shared provenance | UUID BLOB(16) required |
| **PerCell4 (this project)** | **UUID BLOB(16) throughout** |

---

## Action: Store the Following as Context Files

The coding agent should create and maintain these markdown files for use as persistent context in future sessions:

### `context/project_scope.md`
- Lab team size: 3-6 researchers
- Use pattern: individual local `.percell` files, merged for combined analysis
- Planned ML feature: image/label export for particle detection model training
- UI target: napari plugin primary, CLI for batch/power users
- Not a web app, not a server app — local desktop with merge capability

### `context/db_decisions.md`
- Primary DB: SQLite with WAL mode
- ID strategy: UUID stored as BLOB(16) for all entity tables
- Rationale: merge-safety, ML training data stability, multi-user provenance
- Integer IDs only for: log tables and junction tables with no external identity
- Merge strategy: `INSERT OR IGNORE` via SQLite ATTACH

### `context/schema_principles.md`
- Measurements table: long/narrow format `(roi_id, channel, metric, value)` — never wide
- Cell identity: `CELL_IDENTITIES` table with stable UUID as permanent anchor across derived FOVs
- FOV lineage: `lineage_path` text column for fast subtree queries without recursive CTEs
- Derived FOV naming: config-driven suffix system, constructed by `LayerStore` at derivation time
- Analysis layers (segmentations, masks): first-class entities assigned to FOVs via M:N join tables, not stored 1:1

### `context/architecture_overview.md`
- Config format: TOML + Pydantic v2 for validation
- Three-layer split: `ExperimentDB` (SQLite), `LayerStore` (Zarr), `AssignmentService` (logic)
- Pipeline runner resolves `output_tag` references from TOML to DB IDs at execution time
- Every pipeline step writes a `PIPELINE_RUNS` record before executing — provenance is non-negotiable
- Status machine on FOV table with separate `fov_status_log` for transition history
