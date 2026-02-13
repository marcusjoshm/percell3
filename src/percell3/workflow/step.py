"""WorkflowStep base class, supporting dataclasses, and step registry."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class StepInput:
    """Declares an input dependency."""

    name: str
    required: bool = True


@dataclass
class StepOutput:
    """Declares an output this step produces."""

    name: str


@dataclass
class StepParameter:
    """A configurable parameter for a step."""

    name: str
    type: str  # "str", "int", "float", "bool", "choice"
    default: Any = None
    choices: list[str] | None = None
    description: str = ""


@dataclass
class StepResult:
    """Result of executing a workflow step."""

    status: str  # "completed", "failed", "skipped"
    message: str = ""
    outputs_produced: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0


class WorkflowStep(ABC):
    """Base class for all workflow steps.

    Subclasses declare their inputs, outputs, and parameters as properties,
    and implement execute() to perform the actual work.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Step identifier (e.g., 'import_lif', 'segment', 'measure')."""

    @property
    @abstractmethod
    def inputs(self) -> list[StepInput]:
        """What this step needs to run."""

    @property
    @abstractmethod
    def outputs(self) -> list[StepOutput]:
        """What this step produces."""

    @property
    def parameters(self) -> list[StepParameter]:
        """Configurable parameters for this step. Override to declare params."""
        return []

    @abstractmethod
    def execute(
        self,
        store: Any,
        params: dict[str, Any],
        progress_callback: Callable[[float, str], None] | None = None,
    ) -> StepResult:
        """Execute this step against the given store."""

    def can_run(self, store: Any) -> bool:
        """Check if all required inputs are available in the store.

        Default implementation returns True. Steps can override for
        runtime input checking.
        """
        return True


class StepRegistry:
    """Global registry mapping step names to step classes.

    Steps register themselves via the @register decorator or
    by calling StepRegistry.register() directly.
    """

    _registry: dict[str, type[WorkflowStep]] = {}

    @classmethod
    def register(cls, step_class: type[WorkflowStep]) -> type[WorkflowStep]:
        """Register a step class. Can be used as a decorator."""
        instance = step_class()
        cls._registry[instance.name] = step_class
        return step_class

    @classmethod
    def get(cls, name: str) -> type[WorkflowStep]:
        """Look up a step class by name.

        Raises:
            KeyError: If the step name is not registered.
        """
        if name not in cls._registry:
            raise KeyError(
                f"Unknown step '{name}'. "
                f"Registered steps: {sorted(cls._registry.keys())}"
            )
        return cls._registry[name]

    @classmethod
    def list_steps(cls) -> list[str]:
        """Return sorted list of registered step names."""
        return sorted(cls._registry.keys())

    @classmethod
    def clear(cls) -> None:
        """Remove all registered steps. Primarily for testing."""
        cls._registry.clear()
