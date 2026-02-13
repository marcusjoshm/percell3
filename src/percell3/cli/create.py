"""percell3 create — create a new experiment."""

from __future__ import annotations

from pathlib import Path

import click

from percell3.core import ExperimentStore, ExperimentError
from percell3.cli.utils import console, error_handler


@click.command()
@click.argument("path", type=click.Path())
@click.option("--name", "-n", default=None, help="Experiment name.")
@click.option("--description", "-d", default=None, help="Experiment description.")
@error_handler
def create(path: str, name: str | None, description: str | None) -> None:
    """Create a new .percell experiment directory."""
    exp_path = Path(path)
    try:
        store = ExperimentStore.create(
            exp_path, name=name or "", description=description or ""
        )
        store.close()
    except ExperimentError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)

    console.print(f"[green]Created experiment at {exp_path}[/green]")
