"""WorkflowState: persists workflow execution state in SQLite."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from percell3.workflow.step import StepResult


@dataclass
class StepExecution:
    """Record of a single step execution."""

    id: int
    step_name: str
    parameters: dict[str, Any]
    status: str
    message: str
    started_at: str
    completed_at: str | None
    elapsed_seconds: float


class WorkflowState:
    """Persists workflow execution state in SQLite.

    Accepts any object with a ``db_path`` attribute pointing to a SQLite
    database file. This allows it to work with ExperimentStore or any
    mock that exposes db_path.
    """

    def __init__(self, store: Any) -> None:
        self._db_path = Path(store.db_path)
        self._conn = sqlite3.connect(str(self._db_path))
        self._ensure_table()

    @classmethod
    def from_db_path(cls, db_path: Path | str) -> WorkflowState:
        """Create a WorkflowState from a raw database path.

        Useful for testing without ExperimentStore.
        """

        @dataclass
        class _Holder:
            db_path: Path

        holder = _Holder(db_path=Path(db_path))
        return cls(holder)

    def close(self) -> None:
        """Close the cached database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None  # type: ignore[assignment]

    def _connect(self) -> sqlite3.Connection:
        return self._conn

    def _ensure_table(self) -> None:
        conn = self._connect()
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workflow_steps (
                    id INTEGER PRIMARY KEY,
                    step_name TEXT NOT NULL,
                    parameters TEXT,
                    status TEXT NOT NULL,
                    message TEXT,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    elapsed_seconds REAL
                )
                """
            )

    def record_step(
        self,
        step_name: str,
        params: dict[str, Any],
        result: StepResult,
        started_at: str | None = None,
    ) -> None:
        """Record that a step was executed.

        Args:
            step_name: The step identifier.
            params: Parameters that were passed to execute().
            result: The StepResult returned by execute().
            started_at: ISO timestamp when execution started.
                Defaults to now.
        """
        now = datetime.now().isoformat()
        started = started_at or now
        conn = self._connect()
        with conn:
            conn.execute(
                """
                INSERT INTO workflow_steps
                    (step_name, parameters, status, message,
                     started_at, completed_at, elapsed_seconds)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    step_name,
                    json.dumps(params),
                    result.status,
                    result.message,
                    started,
                    now,
                    result.elapsed_seconds,
                ),
            )

    def get_step_history(self, step_name: str) -> list[StepExecution]:
        """Get execution history for a step, ordered newest first."""
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT * FROM workflow_steps
            WHERE step_name = ?
            ORDER BY id DESC
            """,
            (step_name,),
        ).fetchall()

        return [self._row_to_execution(row) for row in rows]

    def last_run(self, step_name: str) -> StepExecution | None:
        """Get the most recent execution of a step, or None."""
        history = self.get_step_history(step_name)
        return history[0] if history else None

    def is_completed(self, step_name: str) -> bool:
        """Check if a step has been successfully completed."""
        last = self.last_run(step_name)
        return last is not None and last.status == "completed"

    @staticmethod
    def _row_to_execution(row: sqlite3.Row) -> StepExecution:
        return StepExecution(
            id=row["id"],
            step_name=row["step_name"],
            parameters=json.loads(row["parameters"]) if row["parameters"] else {},
            status=row["status"],
            message=row["message"] or "",
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            elapsed_seconds=row["elapsed_seconds"] or 0.0,
        )
