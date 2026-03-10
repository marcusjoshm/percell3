"""WorkflowEngine — execute a DAG of workflow steps.

Ported from percell3.workflow with a simplified callable-based step model.
Steps are dataclasses with a handler function rather than ABC subclasses.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from percell4.core.experiment_store import ExperimentStore

logger = logging.getLogger(__name__)


@dataclass(kw_only=True)
class WorkflowStep:
    """A single step in a workflow.

    Attributes:
        name: Unique identifier for the step.
        description: Human-readable description shown in progress output.
        handler: Callable(store, context, **config) -> Any.
        depends_on: List of step names that must complete before this one.
        config: Static keyword arguments passed to handler.
        skip_if: Optional predicate(store, context) -> bool; skip when True.
    """

    name: str
    description: str
    handler: Callable[..., Any]
    depends_on: list[str] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)
    skip_if: Callable[..., bool] | None = None


class WorkflowEngine:
    """Execute a DAG of workflow steps in dependency order.

    Steps are validated at construction time to ensure no cycles exist
    and all dependency references are valid.
    """

    def __init__(self, steps: list[WorkflowStep]) -> None:
        self._steps = {s.name: s for s in steps}
        self._validate_dag()

    @property
    def step_names(self) -> list[str]:
        """Return step names in insertion order."""
        return list(self._steps.keys())

    @property
    def step_count(self) -> int:
        """Return the number of steps."""
        return len(self._steps)

    def get_step(self, name: str) -> WorkflowStep:
        """Return a step by name.

        Raises:
            KeyError: If the step does not exist.
        """
        if name not in self._steps:
            raise KeyError(f"Step {name!r} not in workflow")
        return self._steps[name]

    def _validate_dag(self) -> None:
        """Verify no cycles and all dependencies exist.

        Raises:
            ValueError: If a dependency references a non-existent step
                or a cycle is detected.
        """
        # Check all depends_on references exist
        for step in self._steps.values():
            for dep in step.depends_on:
                if dep not in self._steps:
                    raise ValueError(
                        f"Step {step.name!r} depends on {dep!r}, "
                        f"which does not exist in the workflow"
                    )

        # Check for cycles via topological sort
        try:
            self._topological_order()
        except ValueError:
            raise

    def _topological_order(self) -> list[str]:
        """Return steps in dependency order using Kahn's algorithm.

        Raises:
            ValueError: If the DAG contains a cycle.
        """
        # Build in-degree map
        in_degree: dict[str, int] = {name: 0 for name in self._steps}
        # Build adjacency: for each step, its depends_on are predecessors
        # We need forward edges: dep -> step_name
        forward: dict[str, list[str]] = {name: [] for name in self._steps}
        for step in self._steps.values():
            for dep in step.depends_on:
                forward[dep].append(step.name)
                in_degree[step.name] += 1

        queue: deque[str] = deque(
            name for name, deg in in_degree.items() if deg == 0
        )
        order: list[str] = []

        while queue:
            node = queue.popleft()
            order.append(node)
            for neighbor in forward[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(order) != len(self._steps):
            raise ValueError("Workflow DAG contains a cycle")

        return order

    def run(
        self,
        store: ExperimentStore,
        context: dict[str, Any] | None = None,
        on_step_start: Callable[[str, str], None] | None = None,
        on_step_complete: Callable[[str, str], None] | None = None,
    ) -> dict[str, Any]:
        """Execute all steps in dependency order.

        Args:
            store: ExperimentStore instance.
            context: Shared context dict passed to all step handlers.
                Handlers can read/write to share data between steps.
            on_step_start: Callback(step_name, description) before each step.
            on_step_complete: Callback(step_name, status) after each step.

        Returns:
            Dict mapping step names to result dicts with keys:
                - ``status``: "completed", "skipped", or "failed"
                - ``result``: return value from handler (if completed)
                - ``error``: error message (if failed)
                - ``elapsed``: wall-clock seconds

        Raises:
            Exception: Re-raises the first step failure after recording it.
        """
        if context is None:
            context = {}

        results: dict[str, Any] = {}
        for step_name in self._topological_order():
            step = self._steps[step_name]

            # Check skip condition
            if step.skip_if and step.skip_if(store, context):
                results[step_name] = {"status": "skipped"}
                if on_step_complete:
                    on_step_complete(step_name, "skipped")
                continue

            if on_step_start:
                on_step_start(step_name, step.description)

            start = time.monotonic()
            try:
                result = step.handler(store, context, **step.config)
                elapsed = time.monotonic() - start
                results[step_name] = {
                    "status": "completed",
                    "result": result,
                    "elapsed": elapsed,
                }
            except Exception as e:
                elapsed = time.monotonic() - start
                results[step_name] = {
                    "status": "failed",
                    "error": str(e),
                    "elapsed": elapsed,
                }
                if on_step_complete:
                    on_step_complete(step_name, "failed")
                raise

            if on_step_complete:
                on_step_complete(step_name, "completed")

        return results
