"""SQL query functions for the PerCell 3 core module.

All functions take an open sqlite3.Connection as the first argument.
"""

from __future__ import annotations

import json
import sqlite3

from percell3.core.exceptions import (
    ChannelNotFoundError,
    ConditionNotFoundError,
    DuplicateError,
    RegionNotFoundError,
)
from percell3.core.models import ChannelConfig, CellRecord, MeasurementRecord, RegionInfo

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


def _row_to_region(r: sqlite3.Row) -> RegionInfo:
    """Convert a database row to a RegionInfo."""
    return RegionInfo(
        id=r["id"],
        name=r["name"],
        condition=r["condition"],
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
# Regions
# ---------------------------------------------------------------------------


def insert_region(
    conn: sqlite3.Connection,
    name: str,
    condition_id: int,
    timepoint_id: int | None = None,
    width: int | None = None,
    height: int | None = None,
    pixel_size_um: float | None = None,
    source_file: str | None = None,
    zarr_path: str | None = None,
) -> int:
    # SQLite treats NULLs as distinct in UNIQUE constraints, so check manually
    if timepoint_id is None:
        existing = conn.execute(
            "SELECT id FROM regions WHERE name = ? AND condition_id = ? "
            "AND timepoint_id IS NULL",
            (name, condition_id),
        ).fetchone()
    else:
        existing = conn.execute(
            "SELECT id FROM regions WHERE name = ? AND condition_id = ? "
            "AND timepoint_id = ?",
            (name, condition_id, timepoint_id),
        ).fetchone()
    if existing:
        raise DuplicateError("region", name)
    try:
        cur = conn.execute(
            "INSERT INTO regions (name, condition_id, timepoint_id, width, height, "
            "pixel_size_um, source_file, zarr_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (name, condition_id, timepoint_id, width, height, pixel_size_um,
             source_file, zarr_path),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise DuplicateError("region", name)
    return cur.lastrowid  # type: ignore[return-value]


def select_regions(
    conn: sqlite3.Connection,
    condition_id: int | None = None,
    timepoint_id: int | None = None,
) -> list[RegionInfo]:
    query = (
        "SELECT r.id, r.name, c.name AS condition, t.name AS timepoint, "
        "r.width, r.height, r.pixel_size_um, r.source_file "
        "FROM regions r "
        "JOIN conditions c ON r.condition_id = c.id "
        "LEFT JOIN timepoints t ON r.timepoint_id = t.id"
    )
    params: list = []
    clauses: list[str] = []
    if condition_id is not None:
        clauses.append("r.condition_id = ?")
        params.append(condition_id)
    if timepoint_id is not None:
        clauses.append("r.timepoint_id = ?")
        params.append(timepoint_id)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY r.id"

    rows = conn.execute(query, params).fetchall()
    return [_row_to_region(r) for r in rows]


def select_region_by_name(
    conn: sqlite3.Connection,
    name: str,
    condition_id: int,
    timepoint_id: int | None = None,
) -> RegionInfo:
    if timepoint_id is not None:
        row = conn.execute(
            "SELECT r.id, r.name, c.name AS condition, t.name AS timepoint, "
            "r.width, r.height, r.pixel_size_um, r.source_file "
            "FROM regions r "
            "JOIN conditions c ON r.condition_id = c.id "
            "LEFT JOIN timepoints t ON r.timepoint_id = t.id "
            "WHERE r.name = ? AND r.condition_id = ? AND r.timepoint_id = ?",
            (name, condition_id, timepoint_id),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT r.id, r.name, c.name AS condition, t.name AS timepoint, "
            "r.width, r.height, r.pixel_size_um, r.source_file "
            "FROM regions r "
            "JOIN conditions c ON r.condition_id = c.id "
            "LEFT JOIN timepoints t ON r.timepoint_id = t.id "
            "WHERE r.name = ? AND r.condition_id = ? AND r.timepoint_id IS NULL",
            (name, condition_id),
        ).fetchone()
    if row is None:
        raise RegionNotFoundError(name)
    return _row_to_region(row)


# ---------------------------------------------------------------------------
# Segmentation Runs
# ---------------------------------------------------------------------------


def insert_segmentation_run(
    conn: sqlite3.Connection,
    channel_id: int,
    model_name: str,
    parameters: dict | None = None,
) -> int:
    params_json = json.dumps(parameters) if parameters else None
    cur = conn.execute(
        "INSERT INTO segmentation_runs (channel_id, model_name, parameters) VALUES (?, ?, ?)",
        (channel_id, model_name, params_json),
    )
    conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


def select_segmentation_runs(conn: sqlite3.Connection) -> list[dict]:
    """Return all segmentation runs as dicts."""
    rows = conn.execute(
        "SELECT sr.id, ch.name AS channel, sr.model_name, sr.parameters, "
        "sr.cell_count, sr.created_at "
        "FROM segmentation_runs sr "
        "JOIN channels ch ON sr.channel_id = ch.id "
        "ORDER BY sr.id"
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        if d["parameters"]:
            d["parameters"] = json.loads(d["parameters"])
        result.append(d)
    return result


def update_segmentation_run_cell_count(
    conn: sqlite3.Connection,
    run_id: int,
    cell_count: int,
) -> None:
    conn.execute(
        "UPDATE segmentation_runs SET cell_count = ? WHERE id = ?",
        (cell_count, run_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Cells
# ---------------------------------------------------------------------------


def insert_cells(conn: sqlite3.Connection, cells: list[CellRecord]) -> list[int]:
    """Bulk insert cell records. Returns list of new cell IDs.

    The entire batch is atomic: if any insert fails (e.g. duplicate),
    all inserts are rolled back.
    """
    if not cells:
        return []
    ids: list[int] = []
    try:
        for cell in cells:
            cur = conn.execute(
                "INSERT INTO cells (region_id, segmentation_id, label_value, "
                "centroid_x, centroid_y, bbox_x, bbox_y, bbox_w, bbox_h, "
                "area_pixels, area_um2, perimeter, circularity) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    cell.region_id, cell.segmentation_id, cell.label_value,
                    cell.centroid_x, cell.centroid_y,
                    cell.bbox_x, cell.bbox_y, cell.bbox_w, cell.bbox_h,
                    cell.area_pixels, cell.area_um2, cell.perimeter, cell.circularity,
                ),
            )
            ids.append(cur.lastrowid)  # type: ignore[arg-type]
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        raise DuplicateError("cell", str(cell.label_value))
    return ids


def select_cells(
    conn: sqlite3.Connection,
    condition_id: int | None = None,
    region_id: int | None = None,
    timepoint_id: int | None = None,
    is_valid: bool = True,
    min_area: float | None = None,
    max_area: float | None = None,
    tag_ids: list[int] | None = None,
) -> list[dict]:
    """Query cells with flexible filters. Returns list of row dicts."""
    query = (
        "SELECT c.id, c.region_id, c.segmentation_id, c.label_value, "
        "c.centroid_x, c.centroid_y, c.bbox_x, c.bbox_y, c.bbox_w, c.bbox_h, "
        "c.area_pixels, c.area_um2, c.perimeter, c.circularity, c.is_valid, "
        "r.name AS region_name, cond.name AS condition_name, "
        "t.name AS timepoint_name "
        "FROM cells c "
        "JOIN regions r ON c.region_id = r.id "
        "JOIN conditions cond ON r.condition_id = cond.id "
        "LEFT JOIN timepoints t ON r.timepoint_id = t.id"
    )
    params: list = []
    clauses: list[str] = []

    if is_valid:
        clauses.append("c.is_valid = 1")
    if condition_id is not None:
        clauses.append("r.condition_id = ?")
        params.append(condition_id)
    if region_id is not None:
        clauses.append("c.region_id = ?")
        params.append(region_id)
    if timepoint_id is not None:
        clauses.append("r.timepoint_id = ?")
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
    region_id: int | None = None,
    is_valid: bool = True,
) -> int:
    query = "SELECT COUNT(*) FROM cells c JOIN regions r ON c.region_id = r.id"
    params: list = []
    clauses: list[str] = []
    if is_valid:
        clauses.append("c.is_valid = 1")
    if condition_id is not None:
        clauses.append("r.condition_id = ?")
        params.append(condition_id)
    if region_id is not None:
        clauses.append("c.region_id = ?")
        params.append(region_id)
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
        "INSERT OR REPLACE INTO measurements (cell_id, channel_id, metric, value) "
        "VALUES (?, ?, ?, ?)",
        [(m.cell_id, m.channel_id, m.metric, m.value) for m in measurements],
    )
    conn.commit()


def select_measurements(
    conn: sqlite3.Connection,
    cell_ids: list[int] | None = None,
    channel_ids: list[int] | None = None,
    metrics: list[str] | None = None,
) -> list[dict]:
    query = (
        "SELECT m.cell_id, ch.name AS channel, m.metric, m.value "
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
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY m.cell_id, ch.name, m.metric"

    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Threshold Runs
# ---------------------------------------------------------------------------


def insert_threshold_run(
    conn: sqlite3.Connection,
    channel_id: int,
    method: str,
    parameters: dict | None = None,
) -> int:
    params_json = json.dumps(parameters) if parameters else None
    cur = conn.execute(
        "INSERT INTO threshold_runs (channel_id, method, parameters) VALUES (?, ?, ?)",
        (channel_id, method, params_json),
    )
    conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Analysis Runs
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
