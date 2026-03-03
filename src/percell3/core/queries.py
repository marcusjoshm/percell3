"""SQL query functions for the PerCell 3 core module.

All functions take an open sqlite3.Connection as the first argument.
"""

from __future__ import annotations

import json
import sqlite3

from percell3.core.exceptions import (
    BioRepNotFoundError,
    ChannelNotFoundError,
    ConditionNotFoundError,
    DuplicateError,
    FovNotFoundError,
    SegmentationNotFoundError,
    ThresholdNotFoundError,
)
from percell3.core.models import (
    AnalysisConfig,
    ChannelConfig,
    CellRecord,
    DeleteImpact,
    FovConfigEntry,
    FovInfo,
    MeasurementRecord,
    ParticleRecord,
    SegmentationInfo,
    ThresholdInfo,
)

# ---------------------------------------------------------------------------
# Experiment
# ---------------------------------------------------------------------------


def get_experiment_name(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT name FROM experiments LIMIT 1").fetchone()
    return row["name"] if row else ""


def get_experiment_description(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT description FROM experiments LIMIT 1").fetchone()
    return row["description"] if row else ""


# ---------------------------------------------------------------------------
# Channels
# ---------------------------------------------------------------------------


def insert_channel(
    conn: sqlite3.Connection,
    name: str,
    role: str | None = None,
    color: str | None = None,
    excitation_nm: float | None = None,
    emission_nm: float | None = None,
    is_segmentation: bool = False,
) -> int:
    """Insert a channel. Returns the channel ID."""
    # Compute display_order as current count
    count = conn.execute("SELECT COUNT(*) FROM channels").fetchone()[0]
    try:
        cur = conn.execute(
            "INSERT INTO channels (name, role, excitation_nm, emission_nm, color, "
            "is_segmentation, display_order) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (name, role, excitation_nm, emission_nm, color, int(is_segmentation), count),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise DuplicateError("channel", name)
    return cur.lastrowid  # type: ignore[return-value]


def _row_to_channel(r: sqlite3.Row) -> ChannelConfig:
    """Convert a database row to a ChannelConfig."""
    return ChannelConfig(
        id=r["id"],
        name=r["name"],
        role=r["role"],
        excitation_nm=r["excitation_nm"],
        emission_nm=r["emission_nm"],
        color=r["color"],
        is_segmentation=bool(r["is_segmentation"]),
        display_order=r["display_order"],
    )


def _row_to_fov(r: sqlite3.Row) -> FovInfo:
    """Convert a database row to a FovInfo."""
    return FovInfo(
        id=r["id"],
        display_name=r["display_name"],
        condition=r["condition"],
        bio_rep=r["bio_rep"],
        timepoint=r["timepoint"],
        width=r["width"],
        height=r["height"],
        pixel_size_um=r["pixel_size_um"],
        source_file=r["source_file"],
    )


def select_channels(conn: sqlite3.Connection) -> list[ChannelConfig]:
    rows = conn.execute(
        "SELECT id, name, role, excitation_nm, emission_nm, color, "
        "is_segmentation, display_order FROM channels ORDER BY display_order"
    ).fetchall()
    return [_row_to_channel(r) for r in rows]


def select_channel_by_name(conn: sqlite3.Connection, name: str) -> ChannelConfig:
    row = conn.execute(
        "SELECT id, name, role, excitation_nm, emission_nm, color, "
        "is_segmentation, display_order FROM channels WHERE name = ?",
        (name,),
    ).fetchone()
    if row is None:
        raise ChannelNotFoundError(name)
    return _row_to_channel(row)


# ---------------------------------------------------------------------------
# Conditions
# ---------------------------------------------------------------------------


def insert_condition(
    conn: sqlite3.Connection,
    name: str,
    description: str = "",
) -> int:
    try:
        cur = conn.execute(
            "INSERT INTO conditions (name, description) VALUES (?, ?)",
            (name, description),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise DuplicateError("condition", name)
    return cur.lastrowid  # type: ignore[return-value]


def select_conditions(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT name FROM conditions ORDER BY id").fetchall()
    return [r["name"] for r in rows]


def select_condition_id(conn: sqlite3.Connection, name: str) -> int:
    row = conn.execute("SELECT id FROM conditions WHERE name = ?", (name,)).fetchone()
    if row is None:
        raise ConditionNotFoundError(name)
    return row["id"]


# ---------------------------------------------------------------------------
# Timepoints
# ---------------------------------------------------------------------------


def insert_timepoint(
    conn: sqlite3.Connection,
    name: str,
    time_seconds: float | None = None,
) -> int:
    count = conn.execute("SELECT COUNT(*) FROM timepoints").fetchone()[0]
    try:
        cur = conn.execute(
            "INSERT INTO timepoints (name, time_seconds, display_order) VALUES (?, ?, ?)",
            (name, time_seconds, count),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise DuplicateError("timepoint", name)
    return cur.lastrowid  # type: ignore[return-value]


def select_timepoints(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT name FROM timepoints ORDER BY display_order").fetchall()
    return [r["name"] for r in rows]


def select_timepoint_id(conn: sqlite3.Connection, name: str) -> int | None:
    row = conn.execute("SELECT id FROM timepoints WHERE name = ?", (name,)).fetchone()
    return row["id"] if row else None


# ---------------------------------------------------------------------------
# Biological Replicates
# ---------------------------------------------------------------------------


def insert_bio_rep(conn: sqlite3.Connection, name: str) -> int:
    """Insert an experiment-global biological replicate. Returns the bio rep ID."""
    try:
        cur = conn.execute(
            "INSERT INTO bio_reps (name) VALUES (?)",
            (name,),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise DuplicateError("bio_rep", name)
    return cur.lastrowid  # type: ignore[return-value]


def select_bio_reps(conn: sqlite3.Connection) -> list[str]:
    """Return all bio rep names."""
    rows = conn.execute("SELECT name FROM bio_reps ORDER BY id").fetchall()
    return [r["name"] for r in rows]


def select_bio_rep_by_name(
    conn: sqlite3.Connection,
    name: str,
) -> sqlite3.Row:
    """Look up a bio rep by name.

    Raises BioRepNotFoundError if not found.
    """
    row = conn.execute(
        "SELECT id, name FROM bio_reps WHERE name = ?",
        (name,),
    ).fetchone()
    if row is None:
        raise BioRepNotFoundError(name)
    return row


def select_bio_rep_id(conn: sqlite3.Connection, name: str) -> int:
    """Get bio rep ID by name. Raises BioRepNotFoundError."""
    row = select_bio_rep_by_name(conn, name)
    return row["id"]



# ---------------------------------------------------------------------------
# FOVs
# ---------------------------------------------------------------------------


def insert_fov(
    conn: sqlite3.Connection,
    display_name: str,
    condition_id: int,
    bio_rep_id: int,
    timepoint_id: int | None = None,
    width: int | None = None,
    height: int | None = None,
    pixel_size_um: float | None = None,
    source_file: str | None = None,
) -> int:
    """Insert a FOV with a globally unique display_name. Returns the FOV ID."""
    try:
        cur = conn.execute(
            "INSERT INTO fovs (display_name, condition_id, bio_rep_id, timepoint_id, "
            "width, height, pixel_size_um, source_file) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (display_name, condition_id, bio_rep_id, timepoint_id, width, height,
             pixel_size_um, source_file),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise DuplicateError("fov", display_name)
    return cur.lastrowid  # type: ignore[return-value]


_FOV_SELECT_COLS = (
    "SELECT f.id, f.display_name, c.name AS condition, b.name AS bio_rep, "
    "t.name AS timepoint, "
    "f.width, f.height, f.pixel_size_um, f.source_file "
    "FROM fovs f "
    "JOIN conditions c ON f.condition_id = c.id "
    "JOIN bio_reps b ON f.bio_rep_id = b.id "
    "LEFT JOIN timepoints t ON f.timepoint_id = t.id"
)


def select_fovs(
    conn: sqlite3.Connection,
    condition_id: int | None = None,
    bio_rep_id: int | None = None,
    timepoint_id: int | None = None,
) -> list[FovInfo]:
    query = _FOV_SELECT_COLS
    params: list = []
    clauses: list[str] = []
    if condition_id is not None:
        clauses.append("f.condition_id = ?")
        params.append(condition_id)
    if bio_rep_id is not None:
        clauses.append("f.bio_rep_id = ?")
        params.append(bio_rep_id)
    if timepoint_id is not None:
        clauses.append("f.timepoint_id = ?")
        params.append(timepoint_id)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY f.id"

    rows = conn.execute(query, params).fetchall()
    return [_row_to_fov(r) for r in rows]


def select_fov_by_id(conn: sqlite3.Connection, fov_id: int) -> FovInfo:
    """Look up a FOV by ID. Raises FovNotFoundError."""
    row = conn.execute(
        _FOV_SELECT_COLS + " WHERE f.id = ?", (fov_id,)
    ).fetchone()
    if row is None:
        raise FovNotFoundError(str(fov_id))
    return _row_to_fov(row)


def select_fov_by_display_name(conn: sqlite3.Connection, display_name: str) -> FovInfo:
    """Look up a FOV by display_name. Raises FovNotFoundError."""
    row = conn.execute(
        _FOV_SELECT_COLS + " WHERE f.display_name = ?", (display_name,)
    ).fetchone()
    if row is None:
        raise FovNotFoundError(display_name)
    return _row_to_fov(row)


# ---------------------------------------------------------------------------
# Segmentations (global entities)
# ---------------------------------------------------------------------------


def _row_to_segmentation(row: sqlite3.Row) -> SegmentationInfo:
    """Convert a query result row to a SegmentationInfo."""
    params = json.loads(row["parameters"]) if row["parameters"] else None
    return SegmentationInfo(
        id=row["id"],
        name=row["name"],
        seg_type=row["seg_type"],
        source_fov_id=row["source_fov_id"],
        source_channel=row["source_channel"],
        model_name=row["model_name"],
        parameters=params,
        width=row["width"],
        height=row["height"],
        cell_count=row["cell_count"] or 0,
        created_at=row["created_at"],
    )


_SEG_SELECT_COLS = (
    "SELECT s.id, s.name, s.seg_type, s.source_fov_id, "
    "s.source_channel, s.model_name, s.parameters, "
    "s.width, s.height, s.cell_count, s.created_at "
    "FROM segmentations s"
)


def insert_segmentation(
    conn: sqlite3.Connection,
    name: str,
    seg_type: str,
    width: int,
    height: int,
    source_fov_id: int | None = None,
    source_channel: str | None = None,
    model_name: str = "",
    parameters: dict[str, object] | None = None,
) -> int:
    """Insert a global segmentation entity. Returns the segmentation ID."""
    params_json = json.dumps(parameters) if parameters else None
    try:
        cur = conn.execute(
            "INSERT INTO segmentations (name, seg_type, source_fov_id, source_channel, "
            "model_name, parameters, width, height) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (name, seg_type, source_fov_id, source_channel, model_name,
             params_json, width, height),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise DuplicateError("segmentation", name)
    return cur.lastrowid  # type: ignore[return-value]


def select_segmentations(
    conn: sqlite3.Connection,
    seg_type: str | None = None,
    width: int | None = None,
    height: int | None = None,
) -> list[SegmentationInfo]:
    """Return all segmentations, optionally filtered by type or dimensions."""
    query = _SEG_SELECT_COLS
    params: list = []
    clauses: list[str] = []
    if seg_type is not None:
        clauses.append("s.seg_type = ?")
        params.append(seg_type)
    if width is not None:
        clauses.append("s.width = ?")
        params.append(width)
    if height is not None:
        clauses.append("s.height = ?")
        params.append(height)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY s.id"
    rows = conn.execute(query, params).fetchall()
    return [_row_to_segmentation(r) for r in rows]


def select_segmentation(
    conn: sqlite3.Connection,
    segmentation_id: int,
) -> SegmentationInfo:
    """Return a single segmentation by ID.

    Raises:
        SegmentationNotFoundError: If the segmentation does not exist.
    """
    row = conn.execute(
        _SEG_SELECT_COLS + " WHERE s.id = ?",
        (segmentation_id,),
    ).fetchone()
    if row is None:
        raise SegmentationNotFoundError(segmentation_id)
    return _row_to_segmentation(row)


def rename_segmentation(
    conn: sqlite3.Connection,
    segmentation_id: int,
    new_name: str,
) -> None:
    """Rename a segmentation. Raises DuplicateError on name collision."""
    try:
        conn.execute(
            "UPDATE segmentations SET name = ? WHERE id = ?",
            (new_name, segmentation_id),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        raise DuplicateError("segmentation", new_name)


def delete_segmentation(conn: sqlite3.Connection, segmentation_id: int) -> None:
    """Delete a segmentation. CASCADE handles cells, measurements, fov_config."""
    conn.execute("DELETE FROM segmentations WHERE id = ?", (segmentation_id,))
    conn.commit()


def update_segmentation_cell_count(
    conn: sqlite3.Connection,
    segmentation_id: int,
    cell_count: int,
) -> None:
    conn.execute(
        "UPDATE segmentations SET cell_count = ? WHERE id = ?",
        (cell_count, segmentation_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Thresholds (global entities)
# ---------------------------------------------------------------------------


def _row_to_threshold(row: sqlite3.Row) -> ThresholdInfo:
    """Convert a query result row to a ThresholdInfo."""
    params = json.loads(row["parameters"]) if row["parameters"] else None
    return ThresholdInfo(
        id=row["id"],
        name=row["name"],
        source_fov_id=row["source_fov_id"],
        source_channel=row["source_channel"],
        grouping_channel=row["grouping_channel"],
        method=row["method"],
        parameters=params,
        threshold_value=row["threshold_value"],
        width=row["width"],
        height=row["height"],
        created_at=row["created_at"],
    )


_THR_SELECT_COLS = (
    "SELECT t.id, t.name, t.source_fov_id, t.source_channel, "
    "t.grouping_channel, t.method, t.parameters, t.threshold_value, "
    "t.width, t.height, t.created_at "
    "FROM thresholds t"
)


def insert_threshold(
    conn: sqlite3.Connection,
    name: str,
    method: str,
    width: int,
    height: int,
    source_fov_id: int | None = None,
    source_channel: str | None = None,
    grouping_channel: str | None = None,
    parameters: dict[str, object] | None = None,
) -> int:
    """Insert a global threshold entity. Returns the threshold ID."""
    params_json = json.dumps(parameters) if parameters else None
    try:
        cur = conn.execute(
            "INSERT INTO thresholds (name, source_fov_id, source_channel, "
            "grouping_channel, method, parameters, width, height) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (name, source_fov_id, source_channel, grouping_channel, method,
             params_json, width, height),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise DuplicateError("threshold", name)
    return cur.lastrowid  # type: ignore[return-value]


def select_thresholds(
    conn: sqlite3.Connection,
    width: int | None = None,
    height: int | None = None,
) -> list[ThresholdInfo]:
    """Return all thresholds, optionally filtered by dimensions."""
    query = _THR_SELECT_COLS
    params: list = []
    clauses: list[str] = []
    if width is not None:
        clauses.append("t.width = ?")
        params.append(width)
    if height is not None:
        clauses.append("t.height = ?")
        params.append(height)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY t.id"
    rows = conn.execute(query, params).fetchall()
    return [_row_to_threshold(r) for r in rows]


def select_threshold(
    conn: sqlite3.Connection,
    threshold_id: int,
) -> ThresholdInfo:
    """Return a single threshold by ID.

    Raises:
        ThresholdNotFoundError: If the threshold does not exist.
    """
    row = conn.execute(
        _THR_SELECT_COLS + " WHERE t.id = ?",
        (threshold_id,),
    ).fetchone()
    if row is None:
        raise ThresholdNotFoundError(threshold_id)
    return _row_to_threshold(row)


def rename_threshold(
    conn: sqlite3.Connection,
    threshold_id: int,
    new_name: str,
) -> None:
    """Rename a threshold. Raises DuplicateError on name collision."""
    try:
        conn.execute(
            "UPDATE thresholds SET name = ? WHERE id = ?",
            (new_name, threshold_id),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        raise DuplicateError("threshold", new_name)


def delete_threshold(conn: sqlite3.Connection, threshold_id: int) -> None:
    """Delete a threshold. CASCADE handles particles, measurements, fov_config."""
    conn.execute("DELETE FROM thresholds WHERE id = ?", (threshold_id,))
    conn.commit()


def update_threshold_value(
    conn: sqlite3.Connection,
    threshold_id: int,
    threshold_value: float,
) -> None:
    """Update the threshold value (set after computation)."""
    conn.execute(
        "UPDATE thresholds SET threshold_value = ? WHERE id = ?",
        (threshold_value, threshold_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Cells
# ---------------------------------------------------------------------------


def insert_cells(conn: sqlite3.Connection, cells: list[CellRecord]) -> list[int]:
    """Bulk insert cell records. Returns list of new cell IDs."""
    if not cells:
        return []
    sql = (
        "INSERT INTO cells (fov_id, segmentation_id, label_value, "
        "centroid_x, centroid_y, bbox_x, bbox_y, bbox_w, bbox_h, "
        "area_pixels, area_um2, perimeter, circularity) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )
    rows = [
        (
            cell.fov_id, cell.segmentation_id, cell.label_value,
            cell.centroid_x, cell.centroid_y,
            cell.bbox_x, cell.bbox_y, cell.bbox_w, cell.bbox_h,
            cell.area_pixels, cell.area_um2, cell.perimeter, cell.circularity,
        )
        for cell in cells
    ]
    try:
        conn.executemany(sql, rows)
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        raise DuplicateError("cell", str(cells[-1].label_value))
    last_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    return list(range(last_id - len(cells) + 1, last_id + 1))


def select_cells(
    conn: sqlite3.Connection,
    condition_id: int | None = None,
    bio_rep_id: int | None = None,
    fov_id: int | None = None,
    timepoint_id: int | None = None,
    is_valid: bool = True,
    min_area: float | None = None,
    max_area: float | None = None,
    tag_ids: list[int] | None = None,
) -> list[dict]:
    """Query cells with flexible filters. Returns list of row dicts."""
    query = (
        "SELECT c.id, c.fov_id, c.segmentation_id, c.label_value, "
        "c.centroid_x, c.centroid_y, c.bbox_x, c.bbox_y, c.bbox_w, c.bbox_h, "
        "c.area_pixels, c.area_um2, c.perimeter, c.circularity, c.is_valid, "
        "f.display_name AS fov_name, f.pixel_size_um, "
        "cond.name AS condition_name, "
        "b.name AS bio_rep_name, "
        "t.name AS timepoint_name "
        "FROM cells c "
        "JOIN fovs f ON c.fov_id = f.id "
        "JOIN conditions cond ON f.condition_id = cond.id "
        "JOIN bio_reps b ON f.bio_rep_id = b.id "
        "LEFT JOIN timepoints t ON f.timepoint_id = t.id"
    )
    params: list = []
    clauses: list[str] = []

    if is_valid:
        clauses.append("c.is_valid = 1")
    if condition_id is not None:
        clauses.append("f.condition_id = ?")
        params.append(condition_id)
    if bio_rep_id is not None:
        clauses.append("f.bio_rep_id = ?")
        params.append(bio_rep_id)
    if fov_id is not None:
        clauses.append("c.fov_id = ?")
        params.append(fov_id)
    if timepoint_id is not None:
        clauses.append("f.timepoint_id = ?")
        params.append(timepoint_id)
    if min_area is not None:
        clauses.append("c.area_pixels >= ?")
        params.append(min_area)
    if max_area is not None:
        clauses.append("c.area_pixels <= ?")
        params.append(max_area)
    if tag_ids is not None and len(tag_ids) > 0:
        placeholders = ",".join("?" * len(tag_ids))
        clauses.append(
            f"c.id IN (SELECT cell_id FROM cell_tags WHERE tag_id IN ({placeholders}))"
        )
        params.extend(tag_ids)

    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY c.id"

    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def count_cells(
    conn: sqlite3.Connection,
    condition_id: int | None = None,
    bio_rep_id: int | None = None,
    fov_id: int | None = None,
    is_valid: bool = True,
) -> int:
    needs_fov_join = condition_id is not None or bio_rep_id is not None
    if needs_fov_join:
        query = (
            "SELECT COUNT(*) FROM cells c "
            "JOIN fovs f ON c.fov_id = f.id"
        )
    else:
        query = "SELECT COUNT(*) FROM cells c"
    params: list = []
    clauses: list[str] = []
    if is_valid:
        clauses.append("c.is_valid = 1")
    if condition_id is not None:
        clauses.append("f.condition_id = ?")
        params.append(condition_id)
    if bio_rep_id is not None:
        clauses.append("f.bio_rep_id = ?")
        params.append(bio_rep_id)
    if fov_id is not None:
        clauses.append("c.fov_id = ?")
        params.append(fov_id)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    return conn.execute(query, params).fetchone()[0]


# ---------------------------------------------------------------------------
# Measurements
# ---------------------------------------------------------------------------


def insert_measurements(
    conn: sqlite3.Connection,
    measurements: list[MeasurementRecord],
) -> None:
    conn.executemany(
        "INSERT OR REPLACE INTO measurements "
        "(cell_id, channel_id, metric, value, scope, "
        "segmentation_id, threshold_id, measured_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE(?, datetime('now')))",
        [
            (m.cell_id, m.channel_id, m.metric, m.value,
             m.scope, m.segmentation_id, m.threshold_id, m.measured_at)
            for m in measurements
        ],
    )
    conn.commit()


def select_measurements(
    conn: sqlite3.Connection,
    cell_ids: list[int] | None = None,
    channel_ids: list[int] | None = None,
    metrics: list[str] | None = None,
    scope: str | None = None,
) -> list[dict]:
    query = (
        "SELECT m.cell_id, ch.name AS channel, m.metric, m.value, "
        "m.scope, m.segmentation_id, m.threshold_id, m.measured_at "
        "FROM measurements m "
        "JOIN channels ch ON m.channel_id = ch.id"
    )
    params: list = []
    clauses: list[str] = []
    if cell_ids is not None and len(cell_ids) > 0:
        placeholders = ",".join("?" * len(cell_ids))
        clauses.append(f"m.cell_id IN ({placeholders})")
        params.extend(cell_ids)
    if channel_ids is not None and len(channel_ids) > 0:
        placeholders = ",".join("?" * len(channel_ids))
        clauses.append(f"m.channel_id IN ({placeholders})")
        params.extend(channel_ids)
    if metrics is not None and len(metrics) > 0:
        placeholders = ",".join("?" * len(metrics))
        clauses.append(f"m.metric IN ({placeholders})")
        params.extend(metrics)
    if scope is not None:
        # Include particle summary metrics regardless of scope
        clauses.append(
            "(m.scope = ? OR m.metric IN ("
            "'particle_count','total_particle_area','mean_particle_area',"
            "'max_particle_area','particle_coverage_fraction',"
            "'mean_particle_mean_intensity','mean_particle_integrated_intensity',"
            "'total_particle_integrated_intensity'))"
        )
        params.append(scope)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY m.cell_id, ch.name, m.metric"

    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def select_distinct_measured_channels(conn: sqlite3.Connection) -> list[str]:
    """Return sorted channel names that have at least one measurement."""
    rows = conn.execute(
        "SELECT DISTINCT ch.name FROM measurements m "
        "JOIN channels ch ON m.channel_id = ch.id ORDER BY ch.name"
    ).fetchall()
    return [r[0] for r in rows]


def select_distinct_measured_metrics(conn: sqlite3.Connection) -> list[str]:
    """Return sorted metric names that have at least one measurement."""
    rows = conn.execute(
        "SELECT DISTINCT metric FROM measurements ORDER BY metric"
    ).fetchall()
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# Particles (FOV-level, keyed by fov_id + threshold_id)
# ---------------------------------------------------------------------------


def insert_particles(
    conn: sqlite3.Connection,
    particles: list[ParticleRecord],
) -> None:
    """Bulk insert particle records."""
    if not particles:
        return
    sql = (
        "INSERT INTO particles ("
        "fov_id, threshold_id, label_value, "
        "centroid_x, centroid_y, bbox_x, bbox_y, bbox_w, bbox_h, "
        "area_pixels, area_um2, perimeter, circularity, "
        "eccentricity, solidity, major_axis_length, minor_axis_length, "
        "mean_intensity, max_intensity, integrated_intensity"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )
    rows = [
        (
            p.fov_id, p.threshold_id, p.label_value,
            p.centroid_x, p.centroid_y,
            p.bbox_x, p.bbox_y, p.bbox_w, p.bbox_h,
            p.area_pixels, p.area_um2, p.perimeter, p.circularity,
            p.eccentricity, p.solidity,
            p.major_axis_length, p.minor_axis_length,
            p.mean_intensity, p.max_intensity, p.integrated_intensity,
        )
        for p in particles
    ]
    conn.executemany(sql, rows)
    conn.commit()


def select_particles(
    conn: sqlite3.Connection,
    fov_id: int | None = None,
    threshold_id: int | None = None,
) -> list[dict]:
    """Query particles with optional filters."""
    query = "SELECT * FROM particles"
    params: list = []
    clauses: list[str] = []
    if fov_id is not None:
        clauses.append("fov_id = ?")
        params.append(fov_id)
    if threshold_id is not None:
        clauses.append("threshold_id = ?")
        params.append(threshold_id)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY id"
    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def select_particles_with_context(
    conn: sqlite3.Connection,
    threshold_id: int | None = None,
    fov_id: int | None = None,
) -> list[dict]:
    """Query particles enriched with FOV context (condition, bio rep)."""
    query = (
        "SELECT p.*, "
        "f.display_name AS fov_name, cond.name AS condition_name, br.name AS bio_rep_name "
        "FROM particles p "
        "JOIN fovs f ON p.fov_id = f.id "
        "JOIN conditions cond ON f.condition_id = cond.id "
        "JOIN bio_reps br ON f.bio_rep_id = br.id"
    )
    params: list = []
    clauses: list[str] = []
    if threshold_id is not None:
        clauses.append("p.threshold_id = ?")
        params.append(threshold_id)
    if fov_id is not None:
        clauses.append("p.fov_id = ?")
        params.append(fov_id)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY p.fov_id, p.id"
    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def delete_particles_for_fov(conn: sqlite3.Connection, fov_id: int) -> int:
    """Delete all particles for a FOV.

    Returns:
        Number of particles deleted.
    """
    count = conn.execute(
        "SELECT COUNT(*) FROM particles WHERE fov_id = ?", (fov_id,),
    ).fetchone()[0]
    if count == 0:
        return 0
    conn.execute("DELETE FROM particles WHERE fov_id = ?", (fov_id,))
    conn.commit()
    return count


def delete_particles_for_threshold(
    conn: sqlite3.Connection,
    threshold_id: int,
) -> int:
    """Delete all particles for a specific threshold.

    Returns:
        Number of particles deleted.
    """
    count = conn.execute(
        "SELECT COUNT(*) FROM particles WHERE threshold_id = ?",
        (threshold_id,),
    ).fetchone()[0]
    if count == 0:
        return 0
    conn.execute(
        "DELETE FROM particles WHERE threshold_id = ?",
        (threshold_id,),
    )
    conn.commit()
    return count


def delete_particles_for_fov_threshold(
    conn: sqlite3.Connection,
    fov_id: int,
    threshold_id: int,
) -> int:
    """Delete particles for a specific FOV + threshold combination.

    Returns:
        Number of particles deleted.
    """
    count = conn.execute(
        "SELECT COUNT(*) FROM particles WHERE fov_id = ? AND threshold_id = ?",
        (fov_id, threshold_id),
    ).fetchone()[0]
    if count == 0:
        return 0
    conn.execute(
        "DELETE FROM particles WHERE fov_id = ? AND threshold_id = ?",
        (fov_id, threshold_id),
    )
    conn.commit()
    return count


# ---------------------------------------------------------------------------
# Analysis Config
# ---------------------------------------------------------------------------


def get_or_create_analysis_config(
    conn: sqlite3.Connection,
    experiment_id: int = 1,
) -> AnalysisConfig:
    """Get the analysis config for an experiment, creating one if needed."""
    row = conn.execute(
        "SELECT id, experiment_id, created_at FROM analysis_config "
        "WHERE experiment_id = ? ORDER BY id DESC LIMIT 1",
        (experiment_id,),
    ).fetchone()
    if row is not None:
        return AnalysisConfig(
            id=row["id"],
            experiment_id=row["experiment_id"],
            created_at=row["created_at"],
        )
    cur = conn.execute(
        "INSERT INTO analysis_config (experiment_id) VALUES (?)",
        (experiment_id,),
    )
    conn.commit()
    config_id = cur.lastrowid
    row = conn.execute(
        "SELECT id, experiment_id, created_at FROM analysis_config WHERE id = ?",
        (config_id,),
    ).fetchone()
    return AnalysisConfig(
        id=row["id"],
        experiment_id=row["experiment_id"],
        created_at=row["created_at"],
    )


# ---------------------------------------------------------------------------
# FOV Config (per-FOV segmentation/threshold assignments)
# ---------------------------------------------------------------------------


def insert_fov_config_entry(
    conn: sqlite3.Connection,
    config_id: int,
    fov_id: int,
    segmentation_id: int,
    threshold_id: int | None = None,
    scopes: list[str] | None = None,
) -> int:
    """Add a row to fov_config. Returns the entry ID."""
    scopes_json = json.dumps(scopes or ["whole_cell"])
    cur = conn.execute(
        "INSERT INTO fov_config (config_id, fov_id, segmentation_id, "
        "threshold_id, scopes) VALUES (?, ?, ?, ?, ?)",
        (config_id, fov_id, segmentation_id, threshold_id, scopes_json),
    )
    conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


def select_fov_config(
    conn: sqlite3.Connection,
    config_id: int,
    fov_id: int | None = None,
) -> list[FovConfigEntry]:
    """Return fov_config entries, optionally filtered by FOV."""
    query = (
        "SELECT id, config_id, fov_id, segmentation_id, threshold_id, scopes "
        "FROM fov_config WHERE config_id = ?"
    )
    params: list = [config_id]
    if fov_id is not None:
        query += " AND fov_id = ?"
        params.append(fov_id)
    query += " ORDER BY fov_id, id"
    rows = conn.execute(query, params).fetchall()
    return [
        FovConfigEntry(
            id=r["id"],
            config_id=r["config_id"],
            fov_id=r["fov_id"],
            segmentation_id=r["segmentation_id"],
            threshold_id=r["threshold_id"],
            scopes=json.loads(r["scopes"]) if r["scopes"] else ["whole_cell"],
        )
        for r in rows
    ]


def update_fov_config_entry(
    conn: sqlite3.Connection,
    entry_id: int,
    segmentation_id: int | None = None,
    threshold_id: int | None = None,
    scopes: list[str] | None = None,
) -> None:
    """Update fields on an existing fov_config entry."""
    updates: list[str] = []
    params: list = []
    if segmentation_id is not None:
        updates.append("segmentation_id = ?")
        params.append(segmentation_id)
    if threshold_id is not None:
        updates.append("threshold_id = ?")
        params.append(threshold_id)
    if scopes is not None:
        updates.append("scopes = ?")
        params.append(json.dumps(scopes))
    if not updates:
        return
    params.append(entry_id)
    conn.execute(
        f"UPDATE fov_config SET {', '.join(updates)} WHERE id = ?",
        params,
    )
    conn.commit()


def delete_fov_config_entry(conn: sqlite3.Connection, entry_id: int) -> None:
    """Delete a single fov_config entry."""
    conn.execute("DELETE FROM fov_config WHERE id = ?", (entry_id,))
    conn.commit()


def delete_fov_config_for_fov(
    conn: sqlite3.Connection,
    config_id: int,
    fov_id: int,
) -> None:
    """Delete all config entries for a specific FOV."""
    conn.execute(
        "DELETE FROM fov_config WHERE config_id = ? AND fov_id = ?",
        (config_id, fov_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Cell deletion (re-segmentation)
# ---------------------------------------------------------------------------


def delete_cells_for_fov(conn: sqlite3.Connection, fov_id: int) -> int:
    """Delete all cells (and their measurements/tags) for a FOV.

    Returns:
        Number of cells deleted.
    """
    count = conn.execute(
        "SELECT COUNT(*) FROM cells WHERE fov_id = ?", (fov_id,)
    ).fetchone()[0]
    if count == 0:
        return 0
    conn.execute(
        "DELETE FROM measurements WHERE cell_id IN "
        "(SELECT id FROM cells WHERE fov_id = ?)",
        (fov_id,),
    )
    conn.execute(
        "DELETE FROM cell_tags WHERE cell_id IN "
        "(SELECT id FROM cells WHERE fov_id = ?)",
        (fov_id,),
    )
    conn.execute("DELETE FROM cells WHERE fov_id = ?", (fov_id,))
    conn.commit()
    return count


def select_fov_segmentation_summary(
    conn: sqlite3.Connection,
) -> dict[int, tuple[int, str | None]]:
    """Return {fov_id: (cell_count, last_model_name)} for all FOVs."""
    rows = conn.execute(
        "SELECT f.id AS fov_id, "
        "       COUNT(c.id) AS cell_count, "
        "       s.model_name "
        "FROM fovs f "
        "LEFT JOIN cells c ON c.fov_id = f.id AND c.is_valid = 1 "
        "LEFT JOIN segmentations s ON c.segmentation_id = s.id "
        "GROUP BY f.id "
        "ORDER BY f.id"
    ).fetchall()
    result: dict[int, tuple[int, str | None]] = {}
    for r in rows:
        result[r["fov_id"]] = (r["cell_count"], r["model_name"])
    return result


# ---------------------------------------------------------------------------
# Rename operations
# ---------------------------------------------------------------------------


def rename_experiment(conn: sqlite3.Connection, new_name: str) -> None:
    """Rename the experiment (SQLite only, does not rename the directory)."""
    conn.execute("UPDATE experiments SET name = ?", (new_name,))
    conn.commit()


def rename_condition(conn: sqlite3.Connection, old_name: str, new_name: str) -> None:
    """Rename a condition. Raises ConditionNotFoundError / DuplicateError."""
    cid = select_condition_id(conn, old_name)
    try:
        conn.execute("UPDATE conditions SET name = ? WHERE id = ?", (new_name, cid))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        raise DuplicateError("condition", new_name)


def rename_channel(conn: sqlite3.Connection, old_name: str, new_name: str) -> None:
    """Rename a channel. Raises ChannelNotFoundError / DuplicateError."""
    ch = select_channel_by_name(conn, old_name)
    try:
        conn.execute("UPDATE channels SET name = ? WHERE id = ?", (new_name, ch.id))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        raise DuplicateError("channel", new_name)


def rename_bio_rep(
    conn: sqlite3.Connection,
    old_name: str,
    new_name: str,
) -> None:
    """Rename a biological replicate. Raises BioRepNotFoundError / DuplicateError."""
    row = select_bio_rep_by_name(conn, old_name)
    try:
        conn.execute("UPDATE bio_reps SET name = ? WHERE id = ?", (new_name, row["id"]))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        raise DuplicateError("bio_rep", new_name)


def rename_fov(
    conn: sqlite3.Connection,
    fov_id: int,
    new_display_name: str,
) -> None:
    """Rename a FOV by ID. Raises FovNotFoundError / DuplicateError."""
    existing = conn.execute(
        "SELECT id FROM fovs WHERE id = ?", (fov_id,)
    ).fetchone()
    if existing is None:
        raise FovNotFoundError(str(fov_id))
    try:
        conn.execute(
            "UPDATE fovs SET display_name = ? WHERE id = ?",
            (new_display_name, fov_id),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        raise DuplicateError("fov", new_display_name)


# ---------------------------------------------------------------------------
# Analysis Runs (plugin executions)
# ---------------------------------------------------------------------------


def insert_analysis_run(
    conn: sqlite3.Connection,
    plugin_name: str,
    parameters: dict | None = None,
) -> int:
    params_json = json.dumps(parameters) if parameters else None
    cur = conn.execute(
        "INSERT INTO analysis_runs (plugin_name, parameters) VALUES (?, ?)",
        (plugin_name, params_json),
    )
    conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


def select_analysis_runs(conn: sqlite3.Connection) -> list[dict]:
    """Return all analysis runs as dicts."""
    rows = conn.execute(
        "SELECT id, plugin_name, parameters, status, cell_count, "
        "started_at, completed_at "
        "FROM analysis_runs ORDER BY id"
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        if d["parameters"]:
            d["parameters"] = json.loads(d["parameters"])
        result.append(d)
    return result


def complete_analysis_run(
    conn: sqlite3.Connection,
    run_id: int,
    status: str = "completed",
    cell_count: int | None = None,
) -> None:
    conn.execute(
        "UPDATE analysis_runs SET status = ?, cell_count = ?, "
        "completed_at = datetime('now') WHERE id = ?",
        (status, cell_count, run_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------


def insert_tag(
    conn: sqlite3.Connection,
    name: str,
    color: str | None = None,
) -> int:
    try:
        cur = conn.execute(
            "INSERT INTO tags (name, color) VALUES (?, ?)",
            (name, color),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise DuplicateError("tag", name)
    return cur.lastrowid  # type: ignore[return-value]


def select_tags(conn: sqlite3.Connection) -> list[str]:
    """Return all tag names in creation order."""
    rows = conn.execute("SELECT name FROM tags ORDER BY id").fetchall()
    return [r["name"] for r in rows]


def select_tag_id(conn: sqlite3.Connection, name: str) -> int | None:
    row = conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()
    return row["id"] if row else None


def insert_cell_tags(
    conn: sqlite3.Connection,
    cell_ids: list[int],
    tag_id: int,
) -> None:
    if not cell_ids:
        return
    conn.executemany(
        "INSERT OR IGNORE INTO cell_tags (cell_id, tag_id) VALUES (?, ?)",
        [(cid, tag_id) for cid in cell_ids],
    )
    conn.commit()


def delete_cell_tags(
    conn: sqlite3.Connection,
    cell_ids: list[int],
    tag_id: int,
) -> None:
    if not cell_ids:
        return
    placeholders = ",".join("?" * len(cell_ids))
    conn.execute(
        f"DELETE FROM cell_tags WHERE tag_id = ? AND cell_id IN ({placeholders})",
        [tag_id, *cell_ids],
    )
    conn.commit()


# ---------------------------------------------------------------------------
# FOV Status Cache
# ---------------------------------------------------------------------------


def upsert_fov_status_cache(
    conn: sqlite3.Connection,
    fov_id: int,
    status_json: str,
) -> None:
    """Insert or update the JSON status cache for a FOV."""
    conn.execute(
        "INSERT INTO fov_status_cache (fov_id, status_json, updated_at) "
        "VALUES (?, ?, datetime('now')) "
        "ON CONFLICT(fov_id) DO UPDATE SET "
        "status_json=excluded.status_json, updated_at=excluded.updated_at",
        (fov_id, status_json),
    )
    conn.commit()


def upsert_fov_status_cache_batch(
    conn: sqlite3.Connection,
    fov_ids: list[int],
) -> None:
    """Rebuild the JSON status cache for multiple FOVs.

    Uses fov_config to determine which segmentations and thresholds are
    assigned to each FOV.
    """
    if not fov_ids:
        return
    ph = ",".join("?" * len(fov_ids))
    conn.execute(
        f"""
        WITH seg_data AS (
            SELECT fc.fov_id,
                   json_group_array(json_object(
                       'id', s.id, 'name', s.name, 'cell_count', s.cell_count
                   )) AS segs
            FROM fov_config fc
            JOIN segmentations s ON fc.segmentation_id = s.id
            WHERE fc.fov_id IN ({ph})
            GROUP BY fc.fov_id
        ),
        thresh_data AS (
            SELECT fc.fov_id,
                   json_group_array(json_object(
                       'id', t.id, 'name', t.name,
                       'source_channel', t.source_channel
                   )) AS threshs
            FROM fov_config fc
            JOIN thresholds t ON fc.threshold_id = t.id
            WHERE fc.fov_id IN ({ph}) AND fc.threshold_id IS NOT NULL
            GROUP BY fc.fov_id
        )
        INSERT OR REPLACE INTO fov_status_cache (fov_id, status_json, updated_at)
        SELECT f.id,
               json_object(
                   'segmentations', json(COALESCE(sd.segs, '[]')),
                   'thresholds', json(COALESCE(td.threshs, '[]'))
               ),
               datetime('now')
        FROM fovs f
        LEFT JOIN seg_data sd ON f.id = sd.fov_id
        LEFT JOIN thresh_data td ON f.id = td.fov_id
        WHERE f.id IN ({ph})
        """,
        fov_ids + fov_ids + fov_ids,
    )
    conn.commit()


def select_fov_status_cache(conn: sqlite3.Connection) -> list[dict]:
    """Return all FOV status cache entries."""
    rows = conn.execute(
        "SELECT fov_id, status_json, updated_at FROM fov_status_cache ORDER BY fov_id"
    ).fetchall()
    result = []
    for r in rows:
        d = {"fov_id": r["fov_id"], "updated_at": r["updated_at"]}
        d["status"] = json.loads(r["status_json"]) if r["status_json"] else {}
        result.append(d)
    return result


# ---------------------------------------------------------------------------
# FOV Tags
# ---------------------------------------------------------------------------


def insert_fov_tag(conn: sqlite3.Connection, fov_id: int, tag_id: int) -> None:
    """Tag a FOV. Ignores duplicates."""
    conn.execute(
        "INSERT OR IGNORE INTO fov_tags (fov_id, tag_id) VALUES (?, ?)",
        (fov_id, tag_id),
    )
    conn.commit()


def delete_fov_row(conn: sqlite3.Connection, fov_id: int) -> None:
    """Delete a FOV row from the fovs table.

    CASCADE handles cells, measurements, fov_config,
    fov_status_cache, and fov_tags.
    """
    conn.execute("DELETE FROM fovs WHERE id = ?", (fov_id,))
    conn.commit()


def delete_fov_tag(conn: sqlite3.Connection, fov_id: int, tag_id: int) -> None:
    """Remove a tag from a FOV."""
    conn.execute(
        "DELETE FROM fov_tags WHERE fov_id = ? AND tag_id = ?",
        (fov_id, tag_id),
    )
    conn.commit()


def select_fov_tags(
    conn: sqlite3.Connection,
    fov_id: int | None = None,
) -> list[dict]:
    """Get tags for a specific FOV, or all FOV-tag pairs."""
    if fov_id is not None:
        rows = conn.execute(
            "SELECT t.name, t.color FROM fov_tags ft "
            "JOIN tags t ON ft.tag_id = t.id WHERE ft.fov_id = ? "
            "ORDER BY t.name",
            (fov_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT ft.fov_id, t.name, t.color FROM fov_tags ft "
            "JOIN tags t ON ft.tag_id = t.id ORDER BY ft.fov_id, t.name"
        ).fetchall()
    return [dict(r) for r in rows]


def select_fovs_by_tag(conn: sqlite3.Connection, tag_name: str) -> list[int]:
    """Get all FOV IDs that have a given tag."""
    rows = conn.execute(
        "SELECT ft.fov_id FROM fov_tags ft "
        "JOIN tags t ON ft.tag_id = t.id WHERE t.name = ? "
        "ORDER BY ft.fov_id",
        (tag_name,),
    ).fetchall()
    return [r["fov_id"] for r in rows]


# ---------------------------------------------------------------------------
# Display Name Generation
# ---------------------------------------------------------------------------


def generate_display_name(
    conn: sqlite3.Connection,
    condition_name: str,
    bio_rep_name: str,
    base_name: str = "FOV",
) -> str:
    """Generate a unique display name like 'HS_N1_FOV_001'."""
    prefix = f"{condition_name}_{bio_rep_name}_{base_name}_"
    count = conn.execute(
        "SELECT COUNT(*) FROM fovs WHERE display_name LIKE ?",
        (prefix + "%",),
    ).fetchone()[0]
    candidate = f"{prefix}{count + 1:03d}"

    for attempt in range(2, 101):
        existing = conn.execute(
            "SELECT id FROM fovs WHERE display_name = ?", (candidate,)
        ).fetchone()
        if existing is None:
            return candidate
        candidate = f"{prefix}{count + 1:03d}_{attempt}"

    raise DuplicateError("fov", candidate)


def select_group_tags_for_cells(
    conn: sqlite3.Connection,
    cell_ids: list[int],
) -> list[tuple[int, str]]:
    """Return (cell_id, tag_name) pairs for group tags.

    Batches the query to stay within SQLite's bind parameter limit.
    """
    if not cell_ids:
        return []

    _BATCH_SIZE = 900
    all_rows: list[tuple[int, str]] = []

    for i in range(0, len(cell_ids), _BATCH_SIZE):
        batch = cell_ids[i : i + _BATCH_SIZE]
        placeholders = ",".join("?" * len(batch))
        rows = conn.execute(
            f"""
            SELECT ct.cell_id, t.name
            FROM cell_tags ct
            JOIN tags t ON ct.tag_id = t.id
            WHERE t.name LIKE 'group:%'
              AND ct.cell_id IN ({placeholders})
            ORDER BY ct.cell_id
            """,
            batch,
        ).fetchall()
        all_rows.extend((r[0], r[1]) for r in rows)

    return all_rows


def delete_tags_by_prefix(
    conn: sqlite3.Connection,
    prefix: str,
    cell_ids: list[int] | None = None,
) -> int:
    """Delete cell_tags and tags matching a name prefix."""
    rows = conn.execute(
        "SELECT id FROM tags WHERE name LIKE ?", (prefix + "%",)
    ).fetchall()
    if not rows:
        return 0
    tag_ids = [r["id"] for r in rows]
    ph = ",".join("?" * len(tag_ids))

    if cell_ids is not None and len(cell_ids) > 0:
        cell_ph = ",".join("?" * len(cell_ids))
        count = conn.execute(
            f"SELECT COUNT(*) FROM cell_tags "
            f"WHERE tag_id IN ({ph}) AND cell_id IN ({cell_ph})",
            [*tag_ids, *cell_ids],
        ).fetchone()[0]
        conn.execute(
            f"DELETE FROM cell_tags "
            f"WHERE tag_id IN ({ph}) AND cell_id IN ({cell_ph})",
            [*tag_ids, *cell_ids],
        )
    else:
        count = conn.execute(
            f"SELECT COUNT(*) FROM cell_tags WHERE tag_id IN ({ph})",
            tag_ids,
        ).fetchone()[0]
        conn.execute(
            f"DELETE FROM cell_tags WHERE tag_id IN ({ph})", tag_ids
        )
        conn.execute(f"DELETE FROM tags WHERE id IN ({ph})", tag_ids)

    conn.commit()
    return count


# ---------------------------------------------------------------------------
# Experiment Summary
# ---------------------------------------------------------------------------


def select_experiment_summary(conn: sqlite3.Connection) -> list[dict]:
    """Per-FOV summary: cells, measurements, thresholds, particles."""
    query = """
        SELECT
            f.id AS fov_id,
            f.display_name AS fov_name,
            cond.name AS condition_name,
            b.name AS bio_rep_name,
            f.width, f.height,
            COALESCE(cell_agg.cell_count, 0) AS cells,
            COALESCE(cell_agg.model_name, '') AS seg_model,
            COALESCE(meas_agg.wc_channels, '') AS measured_channels,
            COALESCE(meas_agg.mi_channels, '') AS masked_channels,
            COALESCE(meas_agg.particle_channels, '') AS particle_channels,
            COALESCE(part_agg.particle_count, 0) AS particles
        FROM fovs f
        JOIN conditions cond ON f.condition_id = cond.id
        JOIN bio_reps b ON f.bio_rep_id = b.id
        LEFT JOIN (
            SELECT c.fov_id,
                   COUNT(*) AS cell_count,
                   s.model_name
            FROM cells c
            JOIN segmentations s ON c.segmentation_id = s.id
            WHERE c.is_valid = 1
            GROUP BY c.fov_id
        ) cell_agg ON cell_agg.fov_id = f.id
        LEFT JOIN (
            SELECT c.fov_id,
                GROUP_CONCAT(DISTINCT CASE WHEN m.scope='whole_cell'
                    AND m.metric NOT LIKE 'particle_%'
                    AND m.metric NOT LIKE '%_particle_%'
                    THEN ch.name END) AS wc_channels,
                GROUP_CONCAT(DISTINCT CASE WHEN m.scope='mask_inside'
                    THEN ch.name END) AS mi_channels,
                GROUP_CONCAT(DISTINCT CASE WHEN m.metric='particle_count'
                    THEN ch.name END) AS particle_channels
            FROM measurements m
            JOIN cells c ON m.cell_id = c.id
            JOIN channels ch ON m.channel_id = ch.id
            GROUP BY c.fov_id
        ) meas_agg ON meas_agg.fov_id = f.id
        LEFT JOIN (
            SELECT p.fov_id, COUNT(p.id) AS particle_count
            FROM particles p
            GROUP BY p.fov_id
        ) part_agg ON part_agg.fov_id = f.id
        ORDER BY cond.name, b.name, f.display_name
    """
    rows = conn.execute(query).fetchall()
    return [dict(r) for r in rows]
