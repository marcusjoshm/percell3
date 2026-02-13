"""WorkflowEngine: executes a WorkflowDAG against a store."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable

from percell3.workflow.dag import WorkflowDAG
from percell3.workflow.state import WorkflowState
from percell3.workflow.step import StepResult


class StepStatus(Enum):
    """Status of a step within a workflow run."""

    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class WorkflowResult:
    """Summary of a complete workflow run."""

    steps_completed: int = 0
    steps_skipped: int = 0
    steps_failed: int = 0
    total_elapsed_seconds: float = 0.0
    step_results: dict[str, StepResult] = field(default_factory=dict)


class WorkflowEngine:
    """Executes a WorkflowDAG against a store with state tracking.

    The engine walks the DAG in topological order. For each step it:
    1. Skips if already completed (unless force=True)
    2. Skips if a predecessor failed
    3. Executes the step and records the result in WorkflowState
    4. Stops downstream steps on failure
    """

    def __init__(self, store: Any, dag: WorkflowDAG) -> None:
        self.store = store
        self.dag = dag
        self.state = WorkflowState(store)

    def run(
        self,
        force: bool = False,
        progress_callback: Callable[[str, str], None] | None = None,
    ) -> WorkflowResult:
        """Execute all steps in dependency order.

        Args:
            force: If True, re-run steps even if already completed.
            progress_callback: Called with (step_name, status_msg) for each step.

        Returns:
            WorkflowResult summarizing the run.
        """
        errors = self.dag.validate()
        if errors:
            raise ValueError(
                f"DAG validation failed: {'; '.join(errors)}"
            )

        order = self.dag.execution_order()
        result = WorkflowResult()
        start_time = time.monotonic()
        failed_steps: set[str] = set()

        for step_name in order:
            # Check if any predecessor failed
            predecessors = self.dag.get_predecessors(step_name)
            if any(p in failed_steps for p in predecessors):
                step_result = StepResult(
                    status="skipped",
                    message="Skipped because a predecessor failed",
                )
                result.steps_skipped += 1
                result.step_results[step_name] = step_result
                if progress_callback:
                    progress_callback(step_name, "skipped (predecessor failed)")
                continue

            # Check if already completed
            if not force and self.state.is_completed(step_name):
                step_result = StepResult(
                    status="skipped",
                    message="Already completed",
                )
                result.steps_skipped += 1
                result.step_results[step_name] = step_result
                if progress_callback:
                    progress_callback(step_name, "skipped (already completed)")
                continue

            # Execute the step
            step_result = self._execute_step(step_name)
            result.step_results[step_name] = step_result

            if step_result.status == "completed":
                result.steps_completed += 1
                if progress_callback:
                    progress_callback(step_name, "completed")
            else:
                result.steps_failed += 1
                failed_steps.add(step_name)
                if progress_callback:
                    progress_callback(step_name, f"failed: {step_result.message}")

        result.total_elapsed_seconds = time.monotonic() - start_time
        return result

    def run_step(self, step_name: str, force: bool = False) -> StepResult:
        """Run a single step.

        Args:
            step_name: Name of the step to run.
            force: If True, re-run even if already completed.

        Returns:
            StepResult from executing the step.

        Raises:
            KeyError: If the step doesn't exist in the DAG.
        """
        if not force and self.state.is_completed(step_name):
            return StepResult(
                status="skipped",
                message="Already completed",
            )
        return self._execute_step(step_name)

    def status(self) -> dict[str, StepStatus]:
        """Current status of all steps in the workflow."""
        result: dict[str, StepStatus] = {}
        for name in self.dag.step_names:
            last = self.state.last_run(name)
            if last is None:
                result[name] = StepStatus.PENDING
            elif last.status == "completed":
                result[name] = StepStatus.COMPLETED
            elif last.status == "failed":
                result[name] = StepStatus.FAILED
            else:
                result[name] = StepStatus.SKIPPED
        return result

    def _execute_step(self, step_name: str) -> StepResult:
        """Execute a single step and record the result."""
        step = self.dag.get_step(step_name)
        params = self.dag.get_params(step_name)
        started_at = datetime.now().isoformat()

        start = time.monotonic()
        try:
            step_result = step.execute(self.store, params)
        except Exception as exc:
            step_result = StepResult(
                status="failed",
                message=str(exc),
            )

        step_result.elapsed_seconds = time.monotonic() - start
        self.state.record_step(step_name, params, step_result, started_at=started_at)
        return step_result
