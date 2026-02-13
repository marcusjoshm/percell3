"""YAML serialization for WorkflowDAG.

Requires pyyaml (optional dependency). Raises ImportError with clear
install instructions if pyyaml is not available.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from percell3.workflow.dag import WorkflowDAG
from percell3.workflow.step import StepRegistry


def _require_yaml() -> Any:
    """Import and return the yaml module, or raise a helpful error."""
    try:
        import yaml
        return yaml
    except ImportError:
        raise ImportError(
            "pyyaml is required for workflow serialization. "
            "Install it with: pip install 'percell3[workflow]'"
        ) from None


class WorkflowSerializer:
    """Save and load WorkflowDAG definitions as YAML files.

    The YAML format stores step names, parameters, and explicit edges.
    Steps are resolved via the StepRegistry at load time.
    """

    def save(self, dag: WorkflowDAG, path: Path) -> None:
        """Save a workflow definition to a YAML file.

        Args:
            dag: The WorkflowDAG to serialize.
            path: File path to write.
        """
        yaml = _require_yaml()

        data: dict[str, Any] = {
            "steps": [],
            "edges": [],
        }

        for step_name in dag.step_names:
            step = dag.get_step(step_name)
            entry: dict[str, Any] = {"name": step.name}
            params = dag.get_params(step_name)
            if params:
                entry["params"] = params
            data["steps"].append(entry)

        for src, dst in dag.edges:
            data["edges"].append({"from": src, "to": dst})

        path = Path(path)
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    def load(self, path: Path) -> WorkflowDAG:
        """Load a workflow definition from a YAML file.

        Steps are looked up in the StepRegistry by name. All steps
        referenced in the YAML must be registered before loading.

        Args:
            path: Path to the YAML file.

        Returns:
            A WorkflowDAG with steps and edges as defined in the file.

        Raises:
            KeyError: If a step name in the YAML is not registered.
            FileNotFoundError: If the YAML file doesn't exist.
        """
        yaml = _require_yaml()

        path = Path(path)
        with open(path) as f:
            data = yaml.safe_load(f)

        if not data or "steps" not in data:
            raise ValueError(f"Invalid workflow YAML: missing 'steps' key in {path}")

        dag = WorkflowDAG()

        for step_entry in data["steps"]:
            step_name = step_entry["name"]
            step_cls = StepRegistry.get(step_name)
            params = step_entry.get("params", {})
            dag.add_step(step_cls(), params)

        # Restore explicit edges if present
        for edge in data.get("edges", []):
            dag.connect(edge["from"], edge["to"])

        return dag
