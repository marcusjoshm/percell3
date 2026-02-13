"""PerCell 3 Workflow — DAG-based workflow engine."""

from percell3.workflow.step import (
    StepInput,
    StepOutput,
    StepParameter,
    StepResult,
    StepRegistry,
    WorkflowStep,
)
from percell3.workflow.dag import WorkflowDAG
from percell3.workflow.state import StepExecution, WorkflowState
from percell3.workflow.engine import StepStatus, WorkflowEngine, WorkflowResult
from percell3.workflow.serialization import WorkflowSerializer

# Import defaults to trigger auto-registration of built-in steps
from percell3.workflow import defaults as _defaults  # noqa: F401
from percell3.workflow.defaults import (
    complete_analysis_workflow,
    measure_only_workflow,
)

__all__ = [
    # Step primitives
    "StepInput",
    "StepOutput",
    "StepParameter",
    "StepResult",
    "StepRegistry",
    "WorkflowStep",
    # DAG
    "WorkflowDAG",
    # State
    "StepExecution",
    "WorkflowState",
    # Engine
    "StepStatus",
    "WorkflowEngine",
    "WorkflowResult",
    # Serialization
    "WorkflowSerializer",
    # Preset workflows
    "complete_analysis_workflow",
    "measure_only_workflow",
]
