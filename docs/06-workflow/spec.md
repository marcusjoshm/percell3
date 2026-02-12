# Module 6: Workflow — Specification

## Overview

The workflow engine replaces PerCell 2's linear pipeline with a DAG-based system.
Each step declares its inputs and outputs. Steps can be re-run independently as
long as their inputs exist. The engine resolves execution order automatically.

## WorkflowStep

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

@dataclass
class StepInput:
    """Declares an input dependency."""
    name: str                           # e.g., "images", "labels", "cells"
    required: bool = True

@dataclass
class StepOutput:
    """Declares an output this step produces."""
    name: str                           # e.g., "labels", "measurements"

@dataclass
class StepParameter:
    """A configurable parameter for a step."""
    name: str
    type: str                           # "str", "int", "float", "bool", "choice"
    default: any = None
    choices: list = None                # For "choice" type
    description: str = ""

class WorkflowStep(ABC):
    """Base class for workflow steps."""

    @abstractmethod
    def name(self) -> str:
        """Step identifier (e.g., 'import', 'segment', 'measure')."""

    @abstractmethod
    def inputs(self) -> list[StepInput]:
        """What this step needs to run."""

    @abstractmethod
    def outputs(self) -> list[StepOutput]:
        """What this step produces."""

    @abstractmethod
    def parameters(self) -> list[StepParameter]:
        """Configurable parameters for this step."""

    @abstractmethod
    def execute(self, store: ExperimentStore, params: dict,
                progress_callback=None) -> StepResult:
        """Execute this step."""

    def can_run(self, store: ExperimentStore) -> bool:
        """Check if all required inputs are available."""

@dataclass
class StepResult:
    status: str                         # "completed", "failed", "skipped"
    message: str = ""
    outputs_produced: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0
```

## Built-in Steps

| Step Name | Inputs | Outputs | Wraps |
|-----------|--------|---------|-------|
| `import_lif` | (external file) | images, channels, regions | percell3.io.LifReader |
| `import_tiff` | (external file) | images, channels, regions | percell3.io.TiffDirectoryReader |
| `segment` | images, channels | labels, cells | percell3.segment |
| `measure` | images, labels, cells | measurements | percell3.measure |
| `threshold` | images | masks | percell3.measure.ThresholdEngine |
| `classify` | labels, masks | classifications | percell3.measure.classify_cells |
| `run_plugin` | varies by plugin | measurements, custom | percell3.plugins |
| `export_csv` | measurements | (external file) | ExperimentStore.export_csv |

## DAG Builder

```python
class WorkflowDAG:
    """Directed acyclic graph of workflow steps."""

    def __init__(self):
        self._steps: dict[str, WorkflowStep] = {}
        self._edges: list[tuple[str, str]] = []  # (from_step, to_step)

    def add_step(self, step: WorkflowStep, params: dict = None) -> None:
        """Add a step to the workflow."""

    def connect(self, from_step: str, to_step: str) -> None:
        """Explicitly connect two steps (edge in the DAG)."""

    def auto_connect(self) -> None:
        """Automatically connect steps by matching outputs to inputs."""

    def validate(self) -> list[str]:
        """Validate the DAG:
        - No cycles
        - All required inputs satisfied
        - No orphaned steps
        Returns list of errors (empty = valid).
        """

    def execution_order(self) -> list[str]:
        """Return topological sort of step names."""

    def steps_ready(self, store: ExperimentStore) -> list[str]:
        """Return steps whose inputs are already available."""
```

## Workflow Engine

```python
class WorkflowEngine:
    """Executes a WorkflowDAG against an ExperimentStore."""

    def __init__(self, store: ExperimentStore, dag: WorkflowDAG):
        self.store = store
        self.dag = dag
        self.state = WorkflowState(store)

    def run(self, progress_callback=None) -> WorkflowResult:
        """Execute all steps in dependency order.

        For each step:
        1. Check if already completed (skip if so)
        2. Check if inputs available
        3. Execute step
        4. Record result in state
        """

    def run_step(self, step_name: str, force: bool = False) -> StepResult:
        """Run a single step (re-run if force=True)."""

    def status(self) -> dict[str, StepStatus]:
        """Current status of all steps in the workflow."""

@dataclass
class WorkflowResult:
    steps_completed: int
    steps_skipped: int
    steps_failed: int
    total_elapsed_seconds: float
```

## Workflow State

Tracks what has been run, when, and with what parameters. Stored in the
SQLite database.

```python
class WorkflowState:
    """Persists workflow execution state in SQLite."""

    def __init__(self, store: ExperimentStore):
        self.store = store
        self._ensure_table()

    def record_step(self, step_name: str, params: dict,
                    result: StepResult) -> None:
        """Record that a step was executed."""

    def get_step_history(self, step_name: str) -> list[StepExecution]:
        """Get execution history for a step."""

    def last_run(self, step_name: str) -> Optional[StepExecution]:
        """Get the most recent execution of a step."""

    def is_completed(self, step_name: str) -> bool:
        """Check if a step has been successfully completed."""

# Additional SQL table for workflow state:
# CREATE TABLE IF NOT EXISTS workflow_steps (
#     id INTEGER PRIMARY KEY,
#     step_name TEXT NOT NULL,
#     parameters TEXT,          -- JSON
#     status TEXT NOT NULL,
#     message TEXT,
#     started_at TEXT NOT NULL,
#     completed_at TEXT,
#     elapsed_seconds REAL
# );
```

## Default Workflows

```python
def complete_analysis_workflow(source_path: Path, source_format: str = "lif",
                                channel_seg: str = "DAPI",
                                channels_measure: list[str] = None) -> WorkflowDAG:
    """Standard workflow: import -> segment -> measure -> export."""
    dag = WorkflowDAG()
    dag.add_step(ImportStep(format=source_format), {"path": str(source_path)})
    dag.add_step(SegmentStep(), {"channel": channel_seg})
    dag.add_step(MeasureStep(), {"channels": channels_measure})
    dag.add_step(ExportStep())
    dag.auto_connect()
    return dag

def measure_only_workflow(channels: list[str]) -> WorkflowDAG:
    """For re-measuring with different channels (assumes labels exist)."""
    dag = WorkflowDAG()
    dag.add_step(MeasureStep(), {"channels": channels})
    dag.add_step(ExportStep())
    dag.auto_connect()
    return dag
```

## YAML Serialization

Workflows can be saved/loaded as YAML:

```yaml
# workflow.yaml
name: "Complete Analysis"
steps:
  - name: import_lif
    params:
      path: "data/experiment.lif"
      condition: "control"
  - name: segment
    params:
      channel: "DAPI"
      model: "cyto3"
      diameter: 60
  - name: measure
    params:
      channels: ["GFP", "RFP"]
      metrics: ["mean_intensity", "max_intensity", "integrated_intensity"]
  - name: export_csv
    params:
      path: "results.csv"
```

```python
class WorkflowSerializer:
    def save(self, dag: WorkflowDAG, path: Path) -> None:
        """Save workflow definition as YAML."""

    def load(self, path: Path) -> WorkflowDAG:
        """Load workflow definition from YAML."""
```
