"""percell3 workflow — manage and run workflows."""

from __future__ import annotations

import click
from rich.table import Table

from percell3.cli.utils import console, error_handler, open_experiment
from percell3.workflow import (
    StepRegistry,
    WorkflowEngine,
    complete_analysis_workflow,
    measure_only_workflow,
)


# Available preset workflows
_PRESETS = {
    "complete": {
        "description": "Import -> Segment -> Measure -> Export",
        "factory": complete_analysis_workflow,
    },
    "measure_only": {
        "description": "Re-measure with different channels (assumes labels exist)",
        "factory": measure_only_workflow,
    },
}


@click.group()
def workflow() -> None:
    """Manage and run workflows."""


@workflow.command("list")
@click.option("--steps", is_flag=True, help="Also list registered step types.")
@error_handler
def workflow_list(steps: bool) -> None:
    """List available preset workflows and step types."""
    console.print("\n[bold]Preset Workflows[/bold]\n")
    table = Table(show_header=True)
    table.add_column("Name", style="bold")
    table.add_column("Description")
    for name, info in _PRESETS.items():
        table.add_row(name, info["description"])
    console.print(table)

    if steps:
        console.print("\n[bold]Registered Step Types[/bold]\n")
        step_names = StepRegistry.list_steps()
        step_table = Table(show_header=True)
        step_table.add_column("Step Name", style="bold")
        for s in step_names:
            step_table.add_row(s)
        console.print(step_table)


@workflow.command("run")
@click.argument("name")
@click.option(
    "-e", "--experiment", required=True, type=click.Path(exists=True),
    help="Path to the .percell experiment.",
)
@click.option(
    "--force", is_flag=True,
    help="Force re-run of already completed steps.",
)
@error_handler
def workflow_run(name: str, experiment: str, force: bool) -> None:
    """Run a preset workflow by name."""
    if name not in _PRESETS:
        available = ", ".join(_PRESETS.keys())
        console.print(
            f"[red]Error:[/red] Unknown workflow '{name}'. "
            f"Available: {available}"
        )
        raise SystemExit(1)

    store = open_experiment(experiment)
    try:
        # Build DAG from preset — for now, pass minimal args
        # (full parameterization will come when segment/measure are built)
        factory = _PRESETS[name]["factory"]

        # The factories have different signatures; handle each
        if name == "complete":
            console.print(
                "[yellow]Note:[/yellow] The 'complete' workflow requires "
                "segment and measure modules which are not yet available."
            )
            console.print("Use individual commands (create, import, query) instead.\n")
            return
        elif name == "measure_only":
            console.print(
                "[yellow]Note:[/yellow] The 'measure_only' workflow requires "
                "the measure module which is not yet available."
            )
            return

        dag = factory()  # pragma: no cover
        engine = WorkflowEngine(store, dag)

        def on_progress(step_name: str, status: str) -> None:
            console.print(f"  {step_name}: {status}")

        console.print(f"\n[bold]Running workflow: {name}[/bold]\n")
        result = engine.run(force=force, progress_callback=on_progress)

        console.print(f"\n[green]Workflow complete![/green]")
        console.print(f"  Steps completed: {result.steps_completed}")
        console.print(f"  Steps skipped: {result.steps_skipped}")
        if result.steps_failed:
            console.print(f"  [red]Steps failed: {result.steps_failed}[/red]")
        console.print(f"  Elapsed: {result.total_elapsed_seconds:.1f}s")
    finally:
        store.close()
