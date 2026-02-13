"""WorkflowDAG: directed acyclic graph of workflow steps."""

from __future__ import annotations

from collections import deque
from typing import Any

from percell3.workflow.step import WorkflowStep


class WorkflowDAG:
    """Directed acyclic graph of workflow steps.

    Steps are added with optional parameters. Edges can be created explicitly
    via connect() or inferred automatically via auto_connect() which matches
    step outputs to step inputs by name.
    """

    def __init__(self) -> None:
        self._steps: dict[str, WorkflowStep] = {}
        self._params: dict[str, dict[str, Any]] = {}
        self._edges: list[tuple[str, str]] = []  # (from_step, to_step)

    def add_step(
        self, step: WorkflowStep, params: dict[str, Any] | None = None
    ) -> None:
        """Add a step to the workflow.

        Args:
            step: A WorkflowStep instance.
            params: Parameters to pass to execute().

        Raises:
            ValueError: If a step with the same name already exists.
        """
        if step.name in self._steps:
            raise ValueError(f"Step '{step.name}' already exists in the DAG")
        self._steps[step.name] = step
        self._params[step.name] = params or {}

    def connect(self, from_step: str, to_step: str) -> None:
        """Explicitly connect two steps (edge in the DAG).

        Args:
            from_step: Name of the upstream step.
            to_step: Name of the downstream step.

        Raises:
            KeyError: If either step name is not in the DAG.
            ValueError: If the edge already exists or from==to.
        """
        if from_step not in self._steps:
            raise KeyError(f"Step '{from_step}' not in DAG")
        if to_step not in self._steps:
            raise KeyError(f"Step '{to_step}' not in DAG")
        if from_step == to_step:
            raise ValueError("Cannot connect a step to itself")
        edge = (from_step, to_step)
        if edge not in self._edges:
            self._edges.append(edge)

    def auto_connect(self) -> None:
        """Automatically connect steps by matching outputs to inputs.

        For each step, if another step produces an output whose name matches
        one of this step's inputs, an edge is created from producer to consumer.
        """
        # Build output->step mapping
        output_producers: dict[str, str] = {}
        for name, step in self._steps.items():
            for out in step.outputs:
                output_producers[out.name] = name

        # Connect inputs to matching outputs
        for name, step in self._steps.items():
            for inp in step.inputs:
                if inp.name in output_producers:
                    producer = output_producers[inp.name]
                    if producer != name:
                        self.connect(producer, name)

    def validate(self) -> list[str]:
        """Validate the DAG structure.

        Checks:
        - No cycles (via DFS)
        - No orphaned steps (steps with required inputs that have no
          incoming edges and whose inputs aren't produced by any step)

        Returns:
            List of error messages (empty means valid).
        """
        errors: list[str] = []

        # Check for cycles using DFS
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {name: WHITE for name in self._steps}
        adjacency = self._adjacency_list()

        def dfs(node: str) -> bool:
            color[node] = GRAY
            for neighbor in adjacency.get(node, []):
                if color[neighbor] == GRAY:
                    return True  # cycle found
                if color[neighbor] == WHITE and dfs(neighbor):
                    return True
            color[node] = BLACK
            return False

        for node in self._steps:
            if color[node] == WHITE:
                if dfs(node):
                    errors.append("Cycle detected in workflow DAG")
                    break

        # Check for orphaned steps: steps with required inputs but no
        # incoming edges, and their required inputs aren't produced by anyone
        output_names = set()
        for step in self._steps.values():
            for out in step.outputs:
                output_names.add(out.name)

        incoming = self._incoming_set()
        for name, step in self._steps.items():
            required_inputs = [i for i in step.inputs if i.required]
            if required_inputs and not incoming.get(name):
                unsatisfied = [
                    i.name for i in required_inputs if i.name not in output_names
                ]
                if unsatisfied:
                    errors.append(
                        f"Step '{name}' has unsatisfied required inputs: "
                        f"{unsatisfied}"
                    )

        return errors

    def execution_order(self) -> list[str]:
        """Return topological sort of step names using Kahn's algorithm.

        Raises:
            ValueError: If the DAG contains a cycle.
        """
        in_degree: dict[str, int] = {name: 0 for name in self._steps}
        adjacency = self._adjacency_list()

        for name in self._steps:
            for neighbor in adjacency.get(name, []):
                in_degree[neighbor] += 1

        # Start with nodes that have no incoming edges
        queue: deque[str] = deque(
            name for name, deg in in_degree.items() if deg == 0
        )
        order: list[str] = []

        while queue:
            node = queue.popleft()
            order.append(node)
            for neighbor in adjacency.get(node, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(order) != len(self._steps):
            raise ValueError("Cannot compute execution order: DAG contains a cycle")

        return order

    def get_step(self, name: str) -> WorkflowStep:
        """Get a step by name.

        Raises:
            KeyError: If the step doesn't exist.
        """
        if name not in self._steps:
            raise KeyError(f"Step '{name}' not in DAG")
        return self._steps[name]

    def get_params(self, name: str) -> dict[str, Any]:
        """Get stored parameters for a step."""
        return self._params.get(name, {})

    def get_predecessors(self, name: str) -> list[str]:
        """Get the names of steps that must run before this step."""
        return [src for src, dst in self._edges if dst == name]

    @property
    def step_names(self) -> list[str]:
        """All step names in insertion order."""
        return list(self._steps.keys())

    @property
    def edges(self) -> list[tuple[str, str]]:
        """All edges as (from, to) tuples."""
        return list(self._edges)

    def _adjacency_list(self) -> dict[str, list[str]]:
        """Build forward adjacency list from edges."""
        adj: dict[str, list[str]] = {name: [] for name in self._steps}
        for src, dst in self._edges:
            adj[src].append(dst)
        return adj

    def _incoming_set(self) -> dict[str, set[str]]:
        """Build set of incoming edges for each step."""
        incoming: dict[str, set[str]] = {name: set() for name in self._steps}
        for src, dst in self._edges:
            incoming[dst].add(src)
        return incoming
