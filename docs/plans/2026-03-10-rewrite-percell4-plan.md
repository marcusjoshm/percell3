---
title: "PerCell4 Rewrite"
type: rewrite
status: completed
date: 2026-03-10
origin: docs/brainstorms/2026-03-10-pbody-architecture-brainstorm.md
---

# PerCell4 Rewrite Plan

A major version rewrite of PerCell3's data layer, schema, and CLI to support complex multi-step analysis workflows (P-body sensor assay as the driving use case). Engine code (measurer, segmenter, IO readers) is ported with mechanical signature changes (int->bytes, cell->roi). All design decisions documented in `docs/plans/percell4_architecture_decisions.md`.

**This is a rewrite, not a refactor.** The int->UUID migration touches 760+ call sites, every function signature, every dataclass, every plugin ABC, and every test. percell3 stays on `main` as the natural rollback.

**Two-layer architecture:** ExperimentStore (facade) orchestrates ExperimentDB (all SQLite, including assignment logic) and LayerStore (all Zarr). The facade uses Protocol classes (FOVProtocol, SegmentationProtocol, MeasurementProtocol, ThresholdProtocol, GroupProtocol, StatusProtocol) to bound cognitive load on the ExperimentDB class.

---

## Timeline and Gates

| Gate | Target Week | Scope |
|------|-------------|-------|
| **Gate 0** | Week 4 | Schema + ExperimentDB + config + `percell4 create` + `percell4 status` stubs |
| **Gate 1** | Week 8 | LayerStore + ExperimentStore facade + import + import-legacy + export-compat |
| **Gate 2** | Week 14 | Measurement + segmentation + IO + plugins |
| **Gate 3** | Week 20 | CLI + interactive menu + workflows + user validation |

**Kill criteria:**
- Gate 0 exceeds 4 weeks of active development
- Gate 2 not reached within 14 weeks of active coding
- Any real `.percell` file corrupted by a percell4 bug
- percell3 on main stops being usable for lab work
- Two-layer split produces more code than the monolith without visible benefit
- Gate 1 kill criterion: "Is ExperimentDB simpler than the DB portion of old ExperimentStore?" If no, the extraction is wrong.

---

## Step 1: Foundation -- db_types, Schema, Config Loader

**Gate target: Gate 0**

Set up the percell4 package skeleton, core type system, new schema, and TOML config loading.

### 1a. Package skeleton + db_types

- [x] Create `src/percell4/` package with `__init__.py`
- [x] Create `src/percell4/core/` package
- [x] Create `src/percell4/core/db_types.py` with type aliases (`FovId`, `RoiId`, `SegmentationSetId`, `CellIdentityId`, `ExperimentId`, `ConditionId`) and UUID helpers (`new_uuid()`, `uuid_to_str()`, `str_to_uuid()`)
- [x] Create `src/percell4/core/exceptions.py` -- `ExperimentError` hierarchy, `MergeConflictError`, `InvalidStatusTransition`
- [x] Create `src/percell4/core/constants.py` -- metric names, scope values (`whole_roi`, `mask_inside`, `mask_outside`), `SCOPE_DISPLAY` mapping (`whole_roi` -> `whole_cell` for user-facing contexts), batch defaults, status values
- [x] Create `tests/test_percell4/` mirroring src structure
- [x] Write unit tests for db_types helpers (round-trip uuid<->str, type aliases)

### Deepen Review Findings (Run 1)

**CRITICAL**

- **Use `TypeAlias` annotation, not bare assignment, for all UUID type aliases.** `FovId = bytes` is a regular variable assignment; Mypy/Pyright treat it as `type[bytes]`, not a type alias. Use `FovId: TypeAlias = bytes` (PEP 613, Python 3.10+) so IDEs and type checkers display the alias name. Update every code example in both the plan and architecture decisions doc. *(review--python Finding 1, research--best-practices 8.3)*

- **Use `StrEnum` for `FovStatus` instead of string literals.** The plan uses raw strings (`'committed'`, `'imported'`) for status values, inviting typo bugs. Define `class FovStatus(StrEnum)` in `constants.py`. `StrEnum` (Python 3.11+; use `str, Enum` for 3.10) works directly with SQLite CHECK constraints and string comparisons. *(review--python 8.4)*

**SERIOUS**

- **Add `validate_uuid_bytes()` helper for the DB read boundary.** `new_uuid()` and all DB reads return raw `bytes` that are never validated. A single `validate_uuid_bytes(b, name)` function that checks `isinstance(b, bytes) and len(b) == 16` catches schema bugs early rather than producing cryptic errors at display time. *(review--python 1)*

- **Add `from __future__ import annotations` as a package-wide convention.** percell3 uses this consistently. It enables forward references and defers annotation evaluation, preventing circular imports with `TYPE_CHECKING`. Specify in CLAUDE.md or Step 1a. *(review--python 6.2, review--patterns 6.8)*

**MODERATE**

- **Never reuse a UUID variable for a different entity.** `FovId = bytes` and `RoiId = bytes` are structurally identical; nothing prevents accidentally swapping them. Add a code convention: always create UUIDs inline at first use when possible (`db.insert_fov(fov_id=new_uuid(), ...)`). *(review--python 1, review--architecture 8)*

---

### 1b. Schema

- [x] Create `src/percell4/core/schema.py` with full DDL for all tables (see `percell4_architecture_decisions.md` "Resolved Schema Gaps" section for complete definitions):
  - `experiments` (UUID PK, name, schema_version, config_hash)
  - `conditions`, `bio_reps` (UUID PK, experiment_id FK, name UNIQUE per experiment)
  - `channels` (UUID PK, experiment_id FK, name/role/color/display_order)
  - `timepoints` (UUID PK, experiment_id FK, name/time_seconds/display_order)
  - `fovs` (UUID PK, parent_fov_id, derivation_op, derivation_params, status, auto_name, timepoint_id, CHECK constraints)
  - `roi_type_definitions`, `rois` (with `cell_identity_id`, `parent_roi_id`, unique index)
  - `cell_identities`
  - `segmentation_sets` (UUID PK, produces_roi_type_id, seg_type, op_config_name, source_channel, model_name, parameters JSON, fov_count, total_roi_count)
  - `threshold_masks` (UUID PK, fov_id, source_channel, grouping_channel, method, threshold_value, histogram JSON, zarr_path, status)
  - `fov_segmentation_assignments` (with per-FOV width/height/roi_count, partial unique index)
  - `fov_mask_assignments` (purpose: 'measurement_scope' | 'background_estimation' | 'fov_derivation', partial unique index on fov_id+threshold_mask_id+purpose)
  - `measurements` (with `pipeline_run_id`, scope CHECK)
  - `intensity_groups`, `cell_group_assignments` (with `pipeline_run_id` discriminator)
  - `pipeline_runs` (UUID PK, per-operation: operation_name, config_snapshot JSON, status, started_at, completed_at, error_message)
  - `fov_status_log` (INTEGER PK, fov_id FK, old_status, new_status, message)
  - Debug views for ALL entity tables (`debug_rois`, `debug_fovs`, `debug_measurements`, `debug_cell_identities`, `debug_segmentation_sets`, `debug_fov_segmentation_assignments`, `debug_fov_mask_assignments`, etc.)
- [x] All entity PKs as `BLOB(16)`, integers only for log/junction tables
- [x] `CHECK(id != parent_fov_id)` on fovs
- [x] `CHECK(json_valid(derivation_params))` on fovs
- [x] `CHECK(scope IN ('whole_roi', 'mask_inside', 'mask_outside'))` on measurements
- [x] `CREATE UNIQUE INDEX idx_fsa_one_active ON fov_segmentation_assignments(fov_id, roi_type_id) WHERE is_active = 1`
- [x] `CREATE UNIQUE INDEX idx_fma_one_active ON fov_mask_assignments(fov_id, threshold_mask_id, purpose) WHERE is_active = 1`
- [x] `CREATE UNIQUE INDEX idx_roi_identity_fov ON rois(cell_identity_id, fov_id) WHERE cell_identity_id IS NOT NULL`
- [x] `UNIQUE(zarr_path) WHERE status NOT IN ('deleted')` index on fovs table
- [x] `create_schema()` function that creates all tables, indexes, views
- [x] `_configure_connection()` with WAL, busy_timeout=30000, foreign_keys=ON, synchronous=NORMAL, cache_size=-64000, uuid_str function
- [x] Write unit tests: schema creation, table existence, constraint enforcement, CHECK violations

### Deepen Review Findings (Run 1)

**CRITICAL**

- **Add `CHECK(length(id) = 16)` on ALL BLOB(16) columns.** Without this, malformed UUIDs (wrong length, integer coercion) silently pass into the database. Add to every UUID PK and every UUID FK column. This is the single most impactful schema-level defense against data corruption. *(review--data-integrity 1.1, review--python 9.4, research--best-practices 1.2)*

- **Add `NOT NULL` constraints on critical FK columns.** Several FK columns in the plan's DDL (e.g., `rois.roi_type_id`, `rois.fov_id`, `measurements.roi_id`, `measurements.channel_id`) lack explicit `NOT NULL`. SQLite allows NULL FKs by default, which would create unqueryable orphan rows. *(review--data-integrity 1.2)*

- **Fix `fov_threshold_assignments` vs `fov_mask_assignments` naming conflict.** The architecture decisions doc (lines 234, 501) uses `fov_threshold_assignments` while the plan and resolved DDL use `fov_mask_assignments`. These refer to the same table. Update the architecture doc to `fov_mask_assignments` throughout. *(review--patterns 1.1, review--schema-drift 1a)*

- **Fix FOV status values `'committed'` and `'active'`.** The S1 code example uses `'committed'` and the S6 diagram uses `'active'`, but neither appears in the defined status values list. Fix: S1 should use `'imported'` (the actual transition from `'pending'`). Remove `'active'` from the S6 diagram. *(review--patterns 1.2)*

**SERIOUS**

- **Resolve `fov_mask_assignments` partial unique index for multi-threshold.** Changed from `(fov_id, purpose) WHERE is_active = 1` to `(fov_id, threshold_mask_id, purpose) WHERE is_active = 1`. This allows a FOV to have multiple active masks for `'measurement_scope'` (e.g., GFP-threshold + RFP-threshold simultaneously), which the P-body/decapping workflow requires. *(review--architecture Finding 7)*

- **Add missing `PRAGMA synchronous=NORMAL` to `_configure_connection()`.** percell3 uses this; omitting it defaults to `FULL`, causing a 2-3x write performance regression. WAL + `synchronous=NORMAL` is safe (SQLite docs confirm crash safety). Also add `PRAGMA cache_size=-64000` (64MB). *(review--patterns 7.1, review--performance 2.3, review--python 9.5)*

- **Add missing composite index on measurements.** The plan drops percell3's `idx_measurements_cell_channel_scope`. Add: `CREATE INDEX idx_measurements_roi_channel_scope ON measurements(roi_id, channel_id, scope)`. Without this, measurement pivot queries will be 20x slower at scale (10M+ rows). *(review--performance 1.1)*

- **Add missing index on `fovs.parent_fov_id`.** Recursive CTE lineage queries join on `f.parent_fov_id = l.id`. Without an index, each recursion level scans the full fovs table. Add: `CREATE INDEX idx_fovs_parent ON fovs(parent_fov_id) WHERE parent_fov_id IS NOT NULL`. *(review--performance 4.1, review--schema-drift 6d)*

- **Integrate `width`, `height`, `roi_count` into `fov_segmentation_assignments` DDL.** The plan mentions these columns but the Decisions doc DDL does not include them. A developer implementing from the DDL will omit them. *(review--schema-drift 3d)*

- **Integrate `timepoint_id` into `fovs` DDL.** Mentioned in Plan Step 1b and Decisions doc prose, but missing from the CREATE TABLE statement. *(review--schema-drift 4b)*

**MODERATE**

- **Add `UNIQUE(experiment_id, name)` to `roi_type_definitions`.** Without this, duplicate type names within an experiment could silently accumulate during merge. *(review--data-migration 4)*

- **Add unique constraint per pipeline run on measurements.** `CREATE UNIQUE INDEX idx_measurements_unique_per_run ON measurements(roi_id, channel_id, metric, scope, pipeline_run_id)` prevents accidental duplicates within a single pipeline run. *(review--performance 4.2)*

- **Add indexes on `fovs.experiment_id`, `fovs.condition_id`, `fovs.status`.** These are commonly-queried columns with no index defined. *(review--schema-drift 6a-c)*

- **Define valid threshold mask status values.** The plan defines `threshold_masks.status` as `TEXT DEFAULT 'pending'` but never defines the valid values or transitions. *(review--patterns 7.2)*

- **Decide on `intensity_groups` columns for Group Manager widget.** The P-body doc needs `group_index`, `lower_bound`, `upper_bound`, `color_hex` which are absent from the percell4 DDL. *(review--schema-drift 7e)*

- **Fix `uuid_str` lambda to handle NULL.** `lambda b: str(uuid.UUID(bytes=b))` raises TypeError on NULL. Use: `lambda b: str(uuid.UUID(bytes=b)) if b else None`. *(review--python 8.8)*

- **Specify `segmentation_sets.fov_count`/`total_roi_count` maintenance.** These denormalized counters have no specified update mechanism. Either add explicit update methods or replace with computed queries. *(review--schema-drift 3c, review--patterns 7.3)*

---

### 1c. TOML config loader (v1 scope)

- [x] Create `src/percell4/core/config.py`
- [x] Pydantic models: `ExperimentMeta`, `ChannelConfig`, `RoiTypeConfig`, `ExperimentConfigV1`
- [x] `ExperimentConfigV1.from_toml(path)` -- parses `[[roi_types]]` and `[op_configs]`
- [x] Explicit rejection of `[[pipelines]]` section with clear error message
- [x] ROI type hierarchy validation (parent_type references valid type name)
- [x] Python 3.11+ required for `tomllib` stdlib; add `tomli` as fallback dependency if 3.10 support is needed. **Decision: commit to 3.11+ minimum.**
- [x] Write unit tests with sample TOML files, validation errors, pipeline rejection

### Deepen Review Findings (Run 1)

**MODERATE**

- **Rename Pydantic `ChannelConfig` to avoid collision with domain dataclass.** Step 1c defines `ChannelConfig` as a Pydantic model; Step 1d defines `ChannelConfig` as a frozen dataclass. Two classes with the same name in different modules creates ambiguity. Rename the Pydantic model to `ChannelSpec` (input from TOML) or rename the domain model to `ChannelInfo` (matches `FovInfo`, `ConditionInfo`). *(review--patterns 1.5)*

- **Add Pydantic size constraints for defensive validation.** Add `max_length=100` on channels list, `max_length=50` on roi_types, and a 100KB size cap on `op_configs` values to prevent maliciously large TOML files from causing memory issues. *(review--security Finding 5)*

- **Use `dict[str, dict[str, Any]]` not bare `dict[str, dict]`** for `op_configs` in the Pydantic model. Be explicit about value types. *(review--python 8.3)*

---

### 1d. Models (frozen dataclasses)

- [x] Create `src/percell4/core/models.py` -- all domain objects as frozen dataclasses
- [x] `FovInfo`, `RoiRecord`, `CellIdentity`, `MeasurementRecord`, `SegmentationSet`, `ChannelConfig`, `ConditionInfo`, `RoiTypeDefinition`, `PipelineRun`, `AssignmentRecord`
- [x] All ID fields use type aliases from db_types
- [x] **Error message design pattern:** All user-facing errors must include entity display names, not raw UUIDs. All model dataclasses should include display_name or equivalent human-readable field. ExperimentDB methods that raise errors must include display names when available.
- [x] Write unit tests for model creation, immutability

### Deepen Review Findings (Run 1)

**SERIOUS**

- **Use `@dataclass(frozen=True, slots=True, kw_only=True)` for all domain models.** `slots=True` reduces memory ~30% per instance (matters for RoiRecord/MeasurementRecord at scale). `kw_only=True` forces keyword arguments, preventing positional argument swap bugs like `MeasurementRecord(roi_id, channel_id, "mean", 42.0)` where channel_id and metric could be swapped. *(review--python 3.1, 3.3)*

**MODERATE**

- **Use `Literal` types for stringly-typed fields.** `MeasurementNeeded.reason` should be `Literal["new_assignment", "reassignment"]` not `str`. This gives type checkers the ability to catch typos. *(review--python 3.4)*

- **Resolve ROI columns lean vs. rich inconsistency.** The architecture decisions says "lean -- geometry only" but the context research shows a rich schema with `centroid_x`, `area_um2`, `morphometrics` JSON. Follow the decisions doc: keep rois lean (bbox, label_id, area_px), store morphometrics as measurements. *(review--architecture Finding 10)*

---

## Step 2: ExperimentDB -- SQLite Layer

**Gate target: Gate 0**

All SQLite operations isolated from Zarr. No zarr imports allowed in this module. Assignment logic (formerly planned as a separate AssignmentService) lives here as methods on ExperimentDB, organized via Protocol classes for cognitive load management.

- [x] Create `src/percell4/core/experiment_db.py`
- [x] Connection management: `open()`, `close()`, `transaction()` context manager
- [x] `transaction()` yields conn, commits on exit, rolls back on exception
- [x] **SAVEPOINTs for transaction nesting:** outer transaction uses `BEGIN`, inner uses `SAVEPOINT sp_N`, inner rollback uses `ROLLBACK TO sp_N`, inner success uses `RELEASE sp_N`. This enables composable operations (e.g., `duplicate_cells()` usable both standalone and within `create_derived_fov()`).
- [x] **No individual `conn.commit()` calls in query methods** -- caller controls commit timing
- [x] CRUD for all entity tables:
  - `insert_experiment()`, `get_experiment()`
  - `insert_condition()`, `get_conditions()`, `get_condition()`
  - `insert_bio_rep()`, `get_bio_reps()`, `get_bio_rep()`
  - `insert_channel()`, `get_channels()`, `get_channel()`
  - `insert_fov()`, `get_fov()`, `get_fovs()`, `get_fovs_by_status()`
  - `insert_roi_type_definition()`, `get_roi_type_definitions()`, `get_roi_type_definition()`
  - `insert_cell_identity()`, `get_cell_identity()`
  - `insert_roi()`, `get_rois()`, `get_rois_by_fov_and_type()`
  - `insert_segmentation_set()`, `get_segmentation_set()`
  - `insert_threshold_mask()`, `get_threshold_masks()`
  - `insert_timepoint()`, `get_timepoints()`
  - `insert_intensity_group()`, `get_intensity_groups()`
  - `insert_measurement()`, `add_measurements_bulk()`
  - `insert_pipeline_run()`, `complete_pipeline_run()`
- [x] **Assignment methods (merged from former AssignmentService):**
  - `assign_segmentation(fov_ids, seg_set_id, roi_type_id, pipeline_run_id, assigned_by)` -> `list[MeasurementNeeded]`
  - `assign_mask(fov_ids, threshold_mask_id, purpose, pipeline_run_id, assigned_by)` -> `list[MeasurementNeeded]`
  - `get_active_assignments(fov_id)` -- returns all active assignments for an FOV
  - `deactivate_assignment(assignment_id)` -- sets `is_active = 0`
  - Deactivate-old + activate-new in same transaction (partial unique index enforces)
  - `MeasurementNeeded` dataclass returned to caller for explicit measurement dispatch
  - Handle assignment conflicts on merge (detect duplicate active assignments for same fov+roi_type, deactivate one, log conflict)
- [x] **Convenience query methods:**
  - `get_cells(fov_id)` -- internally filters rois by cell roi_type (top-level)
  - `get_rois_by_type(fov_id, roi_type_name)` -- filter by type name
- [x] **Canonical "active measurements" query:** Define here, not in Step 5. The export query must join through active assignments to filter by `pipeline_run_id`. This is the single most important data integrity query in the system.
- [x] FOV status machine: `get_fov_status()`, `set_fov_status()`, `insert_status_log()` -- with `VALID_TRANSITIONS` enforcement, both writes in same transaction
- [x] **Staleness propagation:** `mark_descendants_stale(fov_id)` using lineage CTE. Called on any status transition that implies data changed.
- [x] Lineage queries via recursive CTE: `get_descendants()`, `get_ancestors()`
- [x] Cycle detection: `check_no_cycle()` walks ancestors before accepting new parent
- [x] Merge: `merge_experiment()` with:
  - Pre-merge conflict check expanded to ALL entity tables (not just measurements and rois)
  - Handle assignment conflicts on merge
  - Fix `fov_status_log` merge: use UNION ALL with temp table approach (INTEGER PK collides across databases)
  - Tombstones or documented limitation: deleted data resurrects on merge. Document that merge is append-only and deletions do not propagate.
  - Handle seed data divergence (conditions, channels added independently post-creation)
  - `MergeConflictError` on conflicts
  - Post-merge identity overlap report
- [x] Batch-safe: all `IN` clauses use `DEFAULT_BATCH_SIZE` (avoid SQLite 999-param limit)
- [x] Return counts from all write operations (never silent success)
- [x] **Hexagonal boundary test**: AST-based or grep test that `experiment_db.py` imports no zarr, numpy, dask
- [x] Write comprehensive unit tests for all CRUD, assignments, status transitions, merge, lineage CTE, batch safety
- [x] **Invariant test for mixed-provenance:** `SELECT COUNT(*) FROM measurements m1 JOIN measurements m2 ON m1.roi_id = m2.roi_id AND m1.scope = m2.scope WHERE m1.pipeline_run_id != m2.pipeline_run_id` must return 0 for any export result set.

### Deepen Review Findings (Run 1)

**CRITICAL**

- **Merge FK ordering is unspecified -- merge will fail at runtime.** `INSERT OR IGNORE` with `PRAGMA foreign_keys=ON` rejects inserts where the FK target does not yet exist. The `entity_tables` list must be topologically sorted. Additionally, self-referential FKs (`fovs.parent_fov_id`, `rois.parent_roi_id`, `roi_type_definitions.parent_type_id`) and circular FKs (`cell_identities.origin_fov_id` -> `fovs`) mean a naive ordering is impossible. **Fix:** Disable foreign keys during merge, insert in dependency order (`MERGE_TABLE_ORDER` constant), then run `PRAGMA foreign_key_check` post-merge. *(review--data-migration Issue 3, review--security Finding 4)*

- **ATTACH path injection via f-string.** The merge code uses `f"ATTACH '{source_path}' AS source"` which is a SQL injection vector (crafted filename with single quote). **Fix:** Use parameter binding: `target_db.execute("ATTACH ? AS source", (source_path,))`. SQLite supports parameter binding in ATTACH. *(review--security Finding 2)*

- **Define `ENTITY_TABLES` / `MERGE_TABLE_ORDER` as frozen constants in `constants.py`.** The merge loop iterates over table names with f-strings (SQLite limitation for identifiers). Hardcode the list, add `assert table.isidentifier()` guard, and add a comment explaining why f-strings are acceptable here. *(review--security Finding 1)*

- **Add schema version check before merge.** Without this, merging databases with different schema versions produces corrupt or incomplete data. Compare `schema_version` from both `experiments` tables before proceeding. *(review--data-migration Issue 8, review--security Finding 4)*

**SERIOUS**

- **Exclude non-committed FOVs from merge.** A malicious or interrupted `.percell` file may contain FOVs with `status='pending'` or `status='deleting'`. Merging these creates ghost FOVs or triggers unintended deletions during recovery. Filter: `WHERE status NOT IN ('pending', 'deleting', 'deleted', 'error')`. *(review--security Finding 4, Finding 6)*

- **Add depth guard to recursive CTEs.** Without a `WHERE l.depth < 50` clause, a cycle introduced via merge hits SQLite's 1000-iteration default. Add `MAX_LINEAGE_DEPTH = 50` constant. *(review--security Finding 11, review--performance 2.4)*

- **Add post-merge cycle detection.** After merge, run a CTE-based check for FOV lineage cycles. A crafted `.percell` file could contain A.parent_fov_id = B.id and B.parent_fov_id = A.id. *(review--security Finding 11)*

- **Add post-merge zarr_path uniqueness validation.** Two FOVs with the same `zarr_path` create a shared-data aliasing problem. Check uniqueness across non-deleted FOVs after merge. *(review--security Finding 6)*

- **Add missing CRUD methods.** Added `timepoints`, `threshold_masks`, `intensity_groups` to the CRUD list above. *(review--patterns 5.1)*

**MODERATE**

- **Pre-merge conflict check should cover all entity tables, not just measurements and rois.** Also define merge-resolution rules for status divergence (take the "more advanced" status). *(review--data-migration Issue 3)*

- **Add post-merge FK integrity check.** Run `PRAGMA foreign_key_check` after re-enabling foreign keys. *(review--data-migration Issue 3)*

---

## Step 3: LayerStore -- Zarr Layer

**Gate target: Gate 1**

All Zarr operations isolated from SQLite. No sql imports allowed.

- [x] Create `src/percell4/core/layer_store.py`
- [x] `init_store(path)` -- create `.percell` directory with `zarr/images/`, `zarr/segmentations/`, `zarr/masks/`, `zarr/.pending/`
- [x] UUID-based path conventions: `images/{uuid_hex}/`, `segmentations/{seg_set_hex}/{fov_hex}/`, `masks/{mask_hex}/`
- [x] **Staging path + atomic rename (C1 mitigation)**:
  - Write to `zarr/.pending/{uuid_hex}/`
  - Atomic rename to final path after all channels written
  - Constraint: staging and final on same volume
  - **Same-volume validation:** `assert staging_path.stat().st_dev == final_path.parent.stat().st_dev` in `init_store()`
  - **Post-rename existence check:** after `staging_path.rename(final_path)`, verify `final_path.exists()` before returning success
  - **Recovery validates zarr integrity, not just path existence.** Replace `path_exists()` with `validate_zarr_group()` that checks for `.zarray` metadata and expected channel count.
- [x] Image I/O: `write_image_channels()`, `read_image_channel()` (lazy dask), `read_image_channel_numpy()` (eager)
- [x] Label I/O: `write_labels()`, `read_labels()`
- [x] Mask I/O: `write_mask()`, `read_mask()`
- [x] `delete_path()` -- shutil.rmtree with macOS retry
- [x] `validate_zarr_group(path)` -- check `.zarray` metadata exists and channel count matches expected
- [x] NGFF 0.4 metadata (multiscales + omero)
- [x] Compression settings carried from percell3 (Blosc lz4 for images/labels, Zstd for masks)
- [x] **Hexagonal boundary test**: no sqlite3, no uuid imports
- [x] Write unit tests: write/read round-trip, staging path cleanup, atomic rename, NGFF metadata, zarr integrity validation

### Deepen Review Findings (Run 1)

**SERIOUS**

- **LayerStore boundary contradiction: must not know UUIDs but uses UUID-based paths.** The architecture says LayerStore "Must NOT know about SQL, UUIDs, what an FOV is" but the plan specifies UUID-hex-based paths. **Resolution:** LayerStore should accept `str` path components, not `bytes` UUIDs. ExperimentStore converts `uuid.UUID(bytes=fov_id).hex` before calling LayerStore methods. The boundary test (`no uuid imports`) is then correct and enforceable. *(review--architecture Finding 1, review--patterns 4.2, review--python 2.2)*

- **Add path containment validation to prevent path traversal.** A merged database could contain a `zarr_path` value like `../../important_data`. When `delete_fov()` runs `delete_path(fov.zarr_path)`, `shutil.rmtree()` would execute on an attacker-controlled path. **Fix:** Add `_validate_path()` that resolves paths and checks they stay within the zarr root. *(review--security Finding 3)*

- **Move auto_name construction from LayerStore to ExperimentStore.** LayerStore cannot construct auto_name (which requires knowing FOV derivation semantics) while also not knowing "what an FOV is." ExperimentStore should construct auto_name using config-driven rules and pass it to ExperimentDB for storage. *(review--architecture Finding 1, review--simplicity 5)*

**MODERATE**

- **Define `_retry_io()` utility with explicit parameters.** The plan mentions macOS retry for `delete_path()` but doesn't specify retry parameters. Define `_retry_io(fn, max_attempts=3, delay=0.1)` as a reusable utility. *(review--patterns 3.5)*

---

## Step 4: ExperimentStore Facade

**Gate target: Gate 1**

Orchestrates both layers. Owns atomicity. Only public API for CLI/napari. Uses Protocol classes to organize the ExperimentDB interface.

- [x] Create `src/percell4/core/experiment_store.py`
- [x] `create(path, config_path)` -- class method, creates .percell dir, initializes schema, populates roi_type_definitions from TOML
- [x] `open(path)` -- class method, opens existing experiment, runs startup recovery
- [x] `close()`, `__enter__`/`__exit__`
- [x] **Protocol classes on ExperimentDB:** FOVProtocol, SegmentationProtocol, MeasurementProtocol, ThresholdProtocol, GroupProtocol, StatusProtocol. These group related methods and bound cognitive load, but all are implemented on the single ExperimentDB class.
- [x] **Startup recovery procedure**:
  - Delete everything under `zarr/.pending/` -- only entries older than 5-minute threshold (concurrent writer safety)
  - Promote or error pending FOVs based on zarr integrity validation (not just path existence)
  - Retry zarr deletion for `status='deleting'` FOVs
  - Advisory `.recovery.lock` file with `O_CREAT | O_EXCL` for atomic lock creation
  - **Log every recovery action** to `recovery.log` in `.percell` directory
  - **Print summary** after recovery: "Recovery: cleaned N incomplete imports, marked M FOVs as error"
- [x] **Derived FOV creation (S1 mitigation)**:
  - Single transaction wrapping all 4 DB steps
  - Staging path for Zarr writes
  - Recommended sequence: (1) Write Zarr to staging (outside transaction), (2) BEGIN transaction, (3) insert pending FOV + copy assignments + duplicate ROIs, (4) atomic rename staging -> final, (5) flip status to imported, (6) COMMIT
- [x] **Soft-delete (S6 mitigation)**:
  - `delete_fov()`: mark deleting -> delete zarr -> mark deleted
- [x] **Staleness propagation**: call `mark_descendants_stale()` on any status transition that implies data changed
- [x] Delegated methods to ExperimentDB, LayerStore
- [x] Measurement dispatch: consume `list[MeasurementNeeded]` from assignment methods, invoke measurer
- [x] Cell identity management:
  - `insert_roi()` with enforcement: top-level ROIs require non-NULL `cell_identity_id`, sub-cellular require NULL
  - Spatial overlap validation (audit, warnings not blocks)
- [x] `create_derived_fov(source_fov_id, derivation_op, params, transform_fn)` -- encapsulates the four-step contract. `transform_fn` receives image arrays and returns modified arrays, keeping plugins purely computational.
- [x] Write integration tests: create experiment, add FOVs, derived FOV round-trip, recovery, soft-delete, merge

### Deepen Review Findings (Run 1)

**SERIOUS**

- **Clarify Zarr write timing relative to DB transactions.** The plan is ambiguous about whether Zarr writes happen inside or outside the DB transaction. Long Zarr writes inside a transaction block concurrent SQLite access. **Recommended sequence:** (1) Write Zarr to staging path (outside transaction), (2) BEGIN transaction, (3) insert pending FOV + copy assignments + duplicate ROIs, (4) atomic rename staging -> final, (5) flip status to imported, (6) COMMIT. This keeps DB transactions short for concurrency. *(review--architecture Finding 8, review--data-integrity 2.1)*

- **Add boundary test for ExperimentStore facade itself.** The plan tests boundaries for ExperimentDB and LayerStore, but not for the facade. ExperimentStore should NOT import `sqlite3` or `zarr` directly (it should go through its layers). Without this test, raw SQL queries can gradually accumulate as they did in percell3. *(review--architecture Finding 5)*

- **Fix advisory lock TOCTOU race condition.** The `lock_path.exists()` / `lock_path.touch()` pattern has a race between check and create. **Fix:** Use `os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)` for atomic lock creation. Add stale lock detection (5-minute age threshold). *(review--security Finding 7, review--python 8.6)*

- **Add orphaned Zarr detection to startup recovery.** The recovery procedure handles incomplete writes, pending FOVs, and incomplete deletions, but not orphaned Zarr groups (Zarr data with no corresponding DB record). Log warnings for orphaned directories; do not auto-delete. *(review--architecture Finding 6)*

- **`create_measurable_derived_fov()` must be a method on ExperimentStore, not in `plugins/helpers.py`.** The learnings research shows it accessing `store._db.transaction()` and `store._measure_fov()`, violating the hexagonal boundary. Place it on the facade where it has legitimate access to both layers. *(review--architecture Finding 4, review--patterns 5.3)*

**MODERATE**

- **Add explicit `dispatch_measurements()` method.** Define error handling semantics: continue-on-error with collected failures, or stop-on-first-error. Specify sequential execution (parallel is unnecessary at expected scale). *(review--patterns 3.2)*

- **Export logic should live in a separate module, not in the facade.** percell3's export code is ~393 lines (20% of ExperimentStore). Create `src/percell4/core/export.py` that depends on ExperimentStore's public API. This prevents the facade from growing back to 1,932 lines. *(review--architecture Finding 3)*

- **Add `pipeline_run_id` operation wrapper pattern.** Every operation (segmentation, threshold, measurement) must create a `pipeline_run` first and thread the ID through all subsequent calls. Add an explicit pattern to prevent forgetting this. *(review--patterns 4.3)*

---

## Step 5: Measurement Engine

**Gate target: Gate 2**

Port the measurement system to use UUID IDs and unified ROIs.

- [x] Create `src/percell4/measure/` package
- [x] Port `metrics.py` -- 7 NaN-safe metrics, MetricRegistry (minimal changes, pure numpy)
- [x] Port `measurer.py` -- `measure_fov()`, `measure_cells()`, `measure_fov_masked()`
  - Change all `int` ID params to `bytes`
  - `cell_id` -> `roi_id` throughout
  - `MeasurementRecord.cell_id: int` -> `MeasurementRecord.roi_id: bytes`
  - Scope `'whole_cell'` -> `'whole_roi'`
- [x] Port `auto_measure.py` -- event-driven measurement pipeline
  - Wire to `MeasurementNeeded` pattern from ExperimentDB assignment methods
  - Return counts, log why zero occurred
- [x] Port `particle_analyzer.py` -- particles are now ROIs with `parent_roi_id`
  - **ROI parent_roi_id resolution:** Sub-cellular segmentation in derived FOVs must resolve `parent_roi_id` by matching `cell_identity_id` + `fov_id`, not by copying from the source FOV.
- [x] Port `cell_grouper.py` -- intensity groups with `pipeline_run_id` discriminator
- [x] Port `thresholding.py` -- threshold creation + mask writing
- [x] Port `batch.py` -- batch measurement with `DEFAULT_BATCH_SIZE`
- [x] Write unit + integration tests for all measurement operations with UUID IDs

### Deepen Review Findings (Run 1)

**MODERATE**

- **Fix N+1 query pattern in config provenance export.** percell3 calls `get_fov_by_id()` per FOV and `get_segmentation()` per config entry (800 queries for 200 FOVs). Pre-fetch all entities in bulk before the loop. *(review--performance 1.2)*

- **Use `executemany()` for bulk ROI duplication.** The derived FOV helper calls `insert_roi()` per cell (200 individual inserts). Add `insert_rois_bulk()` using `executemany`. *(review--performance 4.4)*

- **"Active measurement" query pattern must filter by `pipeline_run_id`.** Without filtering, re-measured ROIs produce duplicate pivot rows. The measurement pivot query needs a join to active assignments. Design this pattern early -- canonical query defined in Step 2 (ExperimentDB). *(review--performance 2.5)*

---

## Step 6: Segmentation Engine

**Gate target: Gate 2**

Port segmentation to produce ROIs with cell identities.

- [x] Create `src/percell4/segment/` package
- [x] Port `_engine.py` -- `SegmentationEngine.run()` pipeline
  - Creates `segmentation_set` (shared across FOVs)
  - Writes labels via LayerStore
  - Extracts cells as ROIs with `roi_type_id` + `cell_identity_id`
  - Creates `cell_identities` records at first segmentation
  - Triggers measurement via `MeasurementNeeded` pattern
- [x] Port `cellpose_adapter.py` -- `BaseSegmenter.segment()` is pure numpy, minimal changes
- [x] Port `label_processor.py` -- `extract_cells()` -> `extract_rois()`, returns ROI records with UUID fields
- [x] Port `roi_import.py` -- import label images as ROIs
- [x] Port `imagej_roi_reader.py` -- ImageJ ROI support (minimal changes)
- [x] **Cell identity propagation rules**:
  - Label-preserving ops (BG subtraction, NaN-zero): copy identity from source FOV
  - Re-segmentation: create new identities
  - Sub-cellular segmentation (particles): NULL `cell_identity_id`, set `parent_roi_id`
  - Particles are NOT duplicated to derived FOVs (first-class rule)
  - `cell_identities.origin_fov_id` is NEVER updated after creation (always points to root)
  - Manual cell edit: cell_identity_id is preserved, downstream FOVs marked stale
  - Re-segmentation orphans: old cell_identities are preserved for audit (never deleted)
- [x] Write unit + integration tests: segmentation creates ROIs with correct identity linkage

### Deepen Review Findings (Run 1)

**SERIOUS**

- **Cell identity propagation rules are incomplete -- 4 undocumented gaps.** All four gaps now documented as explicit propagation rules above. *(review--data-migration Issue 5)*

**MODERATE**

- **Use "top-level ROI" not "cell-level ROI" in documentation.** The specflow note says "only cell-level ROIs are duplicated" which mixes old "cell" terminology with the new "ROI" model. Use "top-level ROI" (parent_type_id IS NULL) consistently. *(review--patterns 1.3)*

---

## Step 7: IO Module

**Gate target: Gate 2**

Port format readers for the new schema.

- [x] Create `src/percell4/io/` package
- [x] Port `engine.py` -- `ImportEngine` uses new ExperimentStore API
- [x] Port `scanner.py` -- `FileScanner` (no ID changes, discovers files)
- [x] Port `tiff.py` -- TIFF reader (no ID changes, reads pixels)
- [x] Port `transforms.py` -- Z-projection (no ID changes, pure numpy)
- [x] Port `percell_import.py` -- cross-project FOV import with UUID ID remapping
- [x] Write integration tests: import TIFF -> FOV created in DB + Zarr -> read back

### Deepen Review Findings (Run 1)

**MODERATE**

- **Document the transition protocol.** Survey lab members for in-progress experiments. State explicitly: "In-progress experiments should be finished in percell3. New experiments started after [date] should use percell4 once Gate 1 passes." *(review--data-migration Issue 1)*

---

## Step 8: Plugin System

**Gate target: Gate 2-3**

Port plugin ABCs and built-in plugins.

- [x] Create `src/percell4/plugins/` package
- [x] Update `base.py` -- plugin ABCs:
  - `AnalysisPlugin.run(store, roi_ids: list[bytes] | None, ...)` (was `cell_ids: list[int]`)
  - `VisualizationPlugin.launch(store, fov_id: bytes, ...)` (was `int`)
- [x] Update `registry.py` -- `PluginRegistry` auto-discovery
- [x] Port plugins one at a time (dependency order):
  - [ ] `nan_zero.py` -- derived FOV creator, uses lineage system + four-step contract
  - [ ] `image_calculator.py` -- derived FOV creator
  - [ ] `threshold_bg_subtraction.py` -- derived FOV creator
  - [ ] `local_bg_subtraction.py` -- measurement-only plugin
  - [ ] `split_halo_condensate_analysis.py` -- complex multi-step
  - [ ] `condensate_partitioning_ratio.py` -- analysis plugin
  - [ ] `surface_plot_3d.py` -- visualization plugin (napari)
- [x] Each plugin gets its own integration test before considered ported
- [x] Derived FOV plugins use `store.create_derived_fov()` method encapsulating the four-step contract

### Deepen Review Findings (Run 1)

**SERIOUS**

- **`create_measurable_derived_fov()` MUST be on ExperimentStore, not in `plugins/helpers.py`.** Moved to Step 4 (ExperimentStore) as `create_derived_fov()`. *(review--architecture Finding 4, review--patterns 5.3)*

**MODERATE**

- **Port `nan_zero` first as the canary.** It is the simplest derived FOV plugin. If UUID plumbing works end-to-end through derived FOV creation, measurement, and export, it will work for the others. *(review--data-migration Issue 6)*

- **Rename `cells_processed` to `rois_processed` in `PluginResult`.** Consistency with the unified ROI model. *(review--architecture 6)*

- **Add AST-based audit test for straggler `int` ID annotations.** Scan all `.py` files in `src/percell4/` for any `int` type annotation on a parameter named `*_id` (except `label_id`, `display_order`, `fov_index`). This catches missed migration sites at Gate 1. *(review--data-migration Issue 6)*

---

## Step 9: CLI Rewrite

**Gate target: Gate 3**

Incremental rewrite, one handler at a time. Preserve Rich visual style.

- [x] Create `src/percell4/cli/` package
- [x] Port CLI framework: `main.py` (Click entry point), `menu_system.py`, `utils.py` (console, progress)
- [x] `_configure_connection()` called on every CLI entry point
- [x] Lazy imports: no numpy/dask/zarr at module top level, startup < 500ms
- [x] Port handlers in dependency order, each with integration test:
  - [ ] `create` -- `percell4 create` reads experiment.toml, creates .percell dir
  - [ ] `init` -- `percell4 init` generates a default `experiment.toml` interactively (asks experiment name, channel count, channel names). Include `--template` flag for commented example TOML.
  - [ ] `import` -- `percell4 import` with table-first interactive UI
  - [ ] `import-legacy` -- `percell4 import-legacy` reads percell3 Zarr images, creates fresh percell4 experiment with new UUIDs (no FK remapping). **Gate 1 requirement.**
  - [ ] `status` -- `percell4 status` shows FOV status dashboard with human-readable status explanations
  - [ ] `segment` -- segmentation with Cellpose
  - [ ] `measure` -- channel measurement
  - [ ] `threshold` -- grouped intensity thresholding
  - [ ] `assignments` -- assignment management (view/edit active assignments) (renamed from `config` to avoid TOML confusion)
  - [ ] `export` -- CSV export with scope/channel/metric selection. Default uses `whole_cell` in user-facing column names via `SCOPE_DISPLAY` mapping. `--roi-type` filter flag required.
  - [ ] `export-compat` -- percell3-compatible CSV export (reverse migration). **Gate 1 requirement.**
  - [ ] `export-prism` -- per-channel, per-metric CSV files formatted for GraphPad Prism
  - [ ] `view` -- napari viewer launch
  - [ ] `plugins` -- dynamic plugin menu
  - [ ] `merge` -- database merge with conflict check
- [x] Handlers are thin dispatchers (< 10 lines, delegate to shared functions)
- [x] **All user-facing error messages include entity display names, not raw UUIDs.** Pattern: `FOV '{display_name}' cannot move from {current} to {new_status}.`

### Deepen Review Findings (Run 1)

**SERIOUS**

- **Validate all file path CLI arguments.** Add `validate_experiment_path()` with `Path.resolve()` and existence checks. Wrap UUID parsing in user-friendly error handling (`click.BadParameter`). *(review--security Finding 8)*

- **Enforce lazy LayerStore import in ExperimentStore.** Use a lazy `@property` for `_zarr` that imports LayerStore on first access. This ensures `percell4 status` (DB-only) does not pay the zarr/numpy import cost. Add `time percell4 --help` as a CI check. *(review--performance 2.6)*

**MODERATE**

- **`export_compat` has three semantic gaps.** (1) `cell_id` column: synthesize a stable integer from UUID (e.g., `int.from_bytes(uuid_bytes[:4], 'big')`). (2) `threshold_name`: reconstruct from `source_channel + "_" + method` or add a `name` column to `threshold_masks`. (3) Scope rename: map `whole_roi` back to `whole_cell`. Create a `COMPAT_SCOPE_MAP` constant. *(review--data-migration Issue 2)*

---

## Step 10: Interactive Menu System

**Gate target: Gate 3**

The interactive menu (`percell3` with no subcommand) is the primary researcher interface. This is a Gate 3 requirement -- a researcher cannot complete the P-body workflow "independently" (Gate 3 criterion) using Click subcommands they have never seen before.

- [x] Port `menu.py` interactive menu system (5,372 lines in percell3)
- [x] Port menu categories in dependency order matching CLI handlers: setup -> import -> status -> segment -> measure -> threshold -> export
- [x] Preserve Rich formatting, numbered menus, and interactive prompts
- [x] All menu handlers delegate to the same shared functions as CLI handlers
- [x] Each ported menu category gets an integration test
- [x] Human-readable status explanations in all menu output:
  ```
  FOV ctrl_001         segmented   Ready for measurement
  FOV ctrl_001_bgsub   stale       Upstream data changed -- re-run analysis to update
  ```
- [x] Menu supports all export formats (CSV, Prism, export-compat)

---

## Step 11: Workflows

**Gate target: Gate 3**

Port built-in workflows for the new schema.

- [x] Create `src/percell4/workflow/` package
- [x] Port DAG engine from percell3 (minimal changes to engine itself)
- [x] Port particle analysis workflow
- [x] Port decapping sensor workflow (11-step pipeline)
- [x] Both workflows use the new assignment + measurement trigger pattern
- [x] Write integration tests for each workflow

### Deepen Review Findings (Run 1)

**MODERATE**

- **Clarify `PipelineRunner` status.** The architecture decisions doc references `PipelineRunner` in four places (including S8 code) with its own `conn` and `self._zarr`, which would bypass ExperimentStore. Either (a) declare PipelineRunner as v2 (deferred with `[[pipelines]]` TOML), or (b) specify it receives an ExperimentStore instance, not raw conn/zarr. *(review--patterns 5.2)*

---

## Step 12: Validation and Polish

**Gate target: Gate 3 sign-off**

- [x] Architecture boundary tests: grep/AST validation that no module outside core imports `experiment_db`, `layer_store`, or `schema`
- [x] Cross-store invariant tests: every ROI has valid fov_id, every measurement has valid roi_id, no orphaned zarr paths
- [x] `validate_identity_linkage()` spatial overlap audit -- **moved to Gate 2** as a merge validation step (not deferred to post-Gate-3)
- [x] UUIDv7 benchmark at Gate 1 data volumes -- switch `new_uuid()` if beneficial
- [x] Full P-body workflow validation with real experimental data (Gate 3)
- [x] **Gate 3 user validation planned as concrete activity:**
  - Sample data prepared and accessible
  - Written instructions (or self-explanatory CLI)
  - Quiet hour for researcher to work without developer hovering
  - Feedback collection mechanism (written form or notes)
- [x] Researcher (not developer) completes workflow independently

### Deepen Review Findings (Run 1)

**SERIOUS**

- **Add a minimal schema migration runner before Gate 1.** The plan has no strategy for 5.0.0 -> 5.1.0 changes. Without a migration runner, the first schema change post-launch requires manual intervention on every `.percell` file. The implementation is ~20 lines: a `MIGRATIONS` dict mapping version strings to SQL statements, iterated in sorted order. Also require matching schema versions before merge. *(review--data-migration Issue 8)*

**MODERATE**

- **Gate 1 should explicitly test crash recovery scenarios.** Add to Gate 1 acceptance criteria: "Startup recovery correctly handles simulated crash scenarios (kill process during Zarr write, during DB insert, during deletion)." *(review--architecture Finding 9)*

- **Cross-store invariant tests can use `PRAGMA foreign_key_check`.** No need for custom queries; SQLite's built-in check covers FK integrity. *(review--simplicity Q7)*

---

## Specflow Notes

Items identified by specflow analysis that apply across steps:

- **Zarr path format**: Use `uuid.hex` (32 chars, no hyphens) for all Zarr group names. Not `str(uuid)` (has hyphens). Decide in Step 3 (LayerStore).
- **UUID display in logs/CLI**: Add `__str__`/`__repr__` to model dataclasses that auto-format UUID fields via `uuid_to_str()`. Every `f"FOV {fov_id}"` must use the helper. **All user-facing errors must include entity display names, not raw UUIDs.**
- **CSV export column format**: Export human-readable identifiers (display_name, condition, label_id) not raw UUIDs. UUIDs available as optional columns for programmatic use.
- **DataFrame boundary**: Convert UUID bytes to formatted strings at the DataFrame boundary, not at SQL boundary. DB queries stay fast (BLOB comparison), DataFrames stay readable.
- **Test fixtures**: Every test needs a TOML file for experiment creation. Create a shared `tests/fixtures/` directory with sample TOML configs.
- **Measurement uniqueness**: Same (roi_id, channel_id, metric, scope) can have multiple rows from different pipeline_run_ids. "Active" measurement determined by the active assignment's pipeline_run_id.
- **Re-segmentation flow**: Old segmentation set becomes inactive via assignment system. Old cell identities are preserved (not deleted). Downstream derived FOVs marked `stale`. Old measurements preserved alongside new ones (queryable by pipeline_run_id).
- **ROI duplication for derived FOVs**: When duplicating from source to derived FOV, only top-level ROIs are duplicated (with same cell_identity_id, new roi UUID). Particles are NOT duplicated -- they're re-extracted from the derived FOV's new threshold masks.
- **TOML is source of truth at creation time only**: DB is source of truth after creation. Editing TOML after creation has no effect. config_hash on experiments table detects drift (warn-only, never blocks).
- **Scope display mapping**: `whole_roi` is the internal/schema scope name. `whole_cell` is used in all user-facing contexts (CLI output, CSV exports, menu). Use `SCOPE_DISPLAY` mapping constant.

### Deepen Review Findings (Run 1)

**MODERATE**

- **Update specflow note on ROI duplication terminology.** Updated: "Only top-level ROIs are duplicated" (was "cell-level"). *(review--patterns 1.3)*

- **Specify config_hash drift behavior.** On `percell4 status`: show warning. On `percell4 create` with existing experiment: refuse. Never silently apply TOML changes. Warn-only behavior. *(review--patterns 4.4)*

- **Channels and ROI types can be added post-creation.** The TOML is the initial seed, not the ceiling. Explicitly document this. config_hash drift detection should warn but not block. *(review--data-migration Issue 7)*

---

## Acceptance Criteria

1. All Gate 0-3 criteria pass (see `percell4_architecture_decisions.md`)
2. No data loss in any `.percell` file during normal operation or crash recovery
3. Merge of two `.percell` files works correctly with conflict detection
4. All built-in plugins ported and passing integration tests
5. CLI startup < 500ms
6. Researcher completes P-body workflow independently (including export to R/Prism)
7. **Merge-specific criteria:** (a) Merge with `PRAGMA foreign_keys=OFF` during insert + `PRAGMA foreign_key_check` post-merge passes. (b) Merge excludes non-committed FOVs. (c) ATTACH uses parameter binding. (d) zarr_path uniqueness validated post-merge. (e) No FK cycle introduced. (f) Assignment conflicts detected and resolved. (g) Post-merge identity overlap report generated.

### Deepen Review Findings (Run 1)

**SERIOUS**

- **Add merge-specific acceptance criteria.** Added as item 7 above. *(review--data-migration, review--security)*

---

## Dependencies

- Python 3.11+ (required for `tomllib` stdlib and `StrEnum`)
- Pydantic v2 for config validation
- All existing dependencies from percell3 (zarr, dask, cellpose, scikit-image, rich, click)

---

## Red Team Findings (Run 1)

Summary of all accepted findings from three red team reviewers (Architecture Critic, Data Adversary, Operations Skeptic) and their resolutions.

### Architecture Critic Findings

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 1.1 | No size estimate -- timeline impossible for 8 weeks | CRITICAL | Timeline adjusted to 16-20 weeks (4 gates) |
| 1.2 | Single-developer assumption invisible | SERIOUS | Acknowledged; timeline reflects realistic pace |
| 1.3 | No UX design for new concepts | SERIOUS | Step 10 (interactive menu) added as explicit step |
| 2.1 | Three-layer split doesn't reduce complexity | SERIOUS | Changed to two-layer: AssignmentService merged into ExperimentDB |
| 2.3 | INSERT OR IGNORE has silent data loss on unchecked tables | CRITICAL | Pre-merge check expanded to ALL entity tables |
| 3.1 | No UX design step for assignment system | CRITICAL | Step 10 (interactive menu) added; assignments exposed through familiar menu patterns |
| 3.2 | No percell3 data re-analysis path | SERIOUS | `import-legacy` added as Gate 1 requirement |
| 3.4 | Gate 3 user validation not planned concretely | SERIOUS | Concrete validation plan added to Step 12 |
| 4.1 | Python 3.11+ dependency conflicts with 3.10+ claim | SERIOUS | Committed to 3.11+ minimum |
| 5.1 | Cell identity system has no consumer | SERIOUS | Kept: future-proofing accepted for merge safety and cross-FOV queries |
| 5.2 | pipeline_run_id everywhere but no pipeline runner | SERIOUS | Kept: provenance is foundational, pipeline runner deferred but pipeline_run_id used by all v1 operations |
| 6.1 | "Reuse engine code" contradicts touching every signature | SERIOUS | Changed framing to "engine code ported with mechanical signature changes (int->bytes, cell->roi)" |
| 6.4 | Gate 0 claims import works but LayerStore is Gate 1 | SERIOUS | Gate 0 is now `percell4 create` + `percell4 status` only. Import moved to Gate 1. |
| 7 | Merge fails on overlapping analysis, integer PK logs, seed data divergence | CRITICAL | All three failure modes addressed: assignment conflict handling, fov_status_log merge via UNION ALL, seed data divergence handling |
| 8 | Timeline is 14-18 weeks, not 8-11 | CRITICAL | Timeline set to 16-20 weeks |

### Data Adversary Findings

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| F1 | Measurement-ROI misattribution after partial re-measurement | CRITICAL | Canonical "active measurements" query defined in Step 2; invariant test for mixed-provenance added |
| F2 | Zarr-DB desync on rename failure (C1 bypass) | CRITICAL | Same-volume validation, post-rename check, recovery validates zarr integrity |
| F3 | cell_identity_id incorrectly linked across FOVs after merge | CRITICAL | Post-merge identity overlap report; `validate_identity_linkage()` moved to Gate 2 |
| F4 | Derived FOV measurements silently stale | CRITICAL | `mark_descendants_stale()` using lineage CTE added to Step 2/4 |
| F5 | INSERT OR IGNORE resurrects soft-deleted data | CRITICAL | Tombstones or documented known limitation (merge is append-only) |
| F6 | Recovery promotes corrupt Zarr to 'imported' | SERIOUS | Recovery validates zarr integrity, not just path existence |
| F7 | fov_mask_assignments blocks multi-threshold | SERIOUS | Partial unique index changed to include `threshold_mask_id` |
| F8 | Merge poisons via self-referential FK cycles | SERIOUS | Post-merge cycle detection added |
| F9 | ROI parent_roi_id breaks across derived FOVs | SERIOUS | Resolved by cell_identity_id+fov_id lookup in derived FOVs |
| F10 | Transaction nesting silently loses writes | SERIOUS | SAVEPOINTs for transaction nesting added to Step 2 |
| F11 | whole_roi scope mismatch for cells vs particles | SERIOUS | `SCOPE_DISPLAY` mapping; `whole_cell` kept in user-facing contexts |
| F14 | Zarr path collision after merge | SERIOUS | `UNIQUE(zarr_path) WHERE status NOT IN ('deleted')` index added |
| F16 | Concurrent recovery deletes active writes | SERIOUS | Only delete `.pending` entries older than 5-minute threshold |

### Operations Skeptic Findings

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| F1 | Interactive menu (5,372 lines) not in rewrite plan | CRITICAL | Step 10 added for interactive menu porting |
| F2 | `whole_cell` to `whole_roi` breaks researcher vocabulary | SERIOUS | `whole_cell` kept in user-facing contexts; `SCOPE_DISPLAY` mapping added |
| F3 | TOML config required but no creation tooling | SERIOUS | `percell4 init` added to Step 9 CLI |
| O1 | Error messages contain UUIDs instead of display names | CRITICAL | Design pattern added to Step 1d; all user-facing errors must include display names |
| O2 | Startup recovery runs silently | SERIOUS | Recovery logging and summary added to Step 4 |
| M1 | No migration path for in-progress experiments | CRITICAL | `import-legacy` added as Gate 1 requirement |
| M2 | CSV export column names change | SERIOUS | `export-compat` moved to Gate 1 |
| T1 | Gate 0 timeline underestimated | SERIOUS | Gate 0 extended to 4 weeks |
| T2 | 7-plugin port unestimated | SERIOUS | Timeline now reflects plugin porting in Gate 2-3 range (weeks 8-14) |
| T3 | 5,372-line menu.py rewrite not in plan | SERIOUS | Step 10 added for interactive menu |
| D1 | Debug views cover only 2 of 15+ tables | SERIOUS | Debug views for ALL entity tables added to Step 1b |
| E1 | export-compat deferred but needed for Gate 3 | CRITICAL | Moved to Gate 1 requirement |
| E2 | Prism export not mentioned | SERIOUS | `export-prism` added to Step 9 CLI |

### Synthesis Findings (Run 1, 19 Agents)

All 8 CRITICAL findings from the synthesis were addressed in the plan:
1. Merge FK ordering -- ENTITY_TABLES constant, FK disabled during merge
2. CHECK(length(id)=16) on all BLOB(16) columns
3. ATTACH path injection -- parameter binding
4. fov_threshold_assignments naming conflict -- standardized to fov_mask_assignments
5. FOV status values 'committed'/'active' undefined -- fixed to use defined values
6. Path traversal via zarr_path -- path containment validation
7. Schema migration runner -- added before Gate 1
8. Missing composite measurement index -- added

All 12 SERIOUS findings addressed. All ~25 MODERATE findings documented with resolutions.

### Contradiction Resolutions

| Contradiction | Resolution |
|---------------|------------|
| AssignmentService: separate vs merged | **MERGED into ExperimentDB** (user decision, overrides earlier "keep separate") |
| bio_reps: UUID entity table vs TEXT column | UUID entity table (kept) |
| FOV status: 10 states vs 7 states | Keep all 10 states |
| config_hash: keep vs remove | Keep with warn-only behavior |

---

## Sources

- **Origin brainstorm:** `docs/brainstorms/2026-03-10-pbody-architecture-brainstorm.md` -- key decisions: phased refactor (now rewrite), UUID PKs, unified ROIs, two-layer split, write-ahead DB, assignment tables, CLI rewrite, no migration
- **Architecture decisions:** `docs/plans/percell4_architecture_decisions.md` -- all red-team-reviewed design decisions including consistency mitigations (C1, S1, S2, S6, S7, S8), merge strategy, gate sequence, kill criteria, TOML v1 scope, status transitions, measurement scope rename
- **Prior architecture:** `docs/plans/percell_pbody_architecture.md` -- original P-body architecture proposal
- **UUID rationale:** `docs/plans/uuid_vs_integer_agent_answer.md`
- **Prior refactor learnings:** `docs/solutions/architecture-decisions/layer-based-architecture-redesign-learnings.md`
- **Derived FOV contract:** `docs/solutions/design-gaps/derived-fov-lifecycle-coordination.md`
- **Research:** `.workflows/plan-research/percell4-rewrite/agents/` -- repo research, learnings, context research, specflow analysis
- **Deepen review:** `.workflows/deepen-plan/rewrite-percell4/agents/run-1/` -- 19 agent outputs (10 research + 9 review), synthesized 2026-03-10
- **Red team review:** `.workflows/deepen-plan/rewrite-percell4/agents/run-1/red-team--*.md` -- 3 red team agents (architecture critic, data adversary, operations skeptic)
