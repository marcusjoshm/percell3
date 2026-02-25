"""percell3 create — create a new experiment."""

from __future__ import annotations

from pathlib import Path

import click

from percell3.cli.utils import console, error_handler


@click.command()
@click.argument("path", type=click.Path())
@click.option("--name", "-n", default=None, help="Experiment name.")
@click.option("--description", "-d", default=None, help="Experiment description.")
@click.option("--overwrite", is_flag=True, default=False, help="Overwrite existing non-empty directory.")
@error_handler
def create(path: str, name: str | None, description: str | None, overwrite: bool) -> None:
    """Create a new .percell experiment directory."""
    from percell3.core import ExperimentStore

    exp_path = Path(path)
    store = ExperimentStore.create(
        exp_path, name=name or "", description=description or "",
        overwrite=overwrite,
    )
    store.close()
    console.print(f"[green]Created experiment at {exp_path}[/green]")
