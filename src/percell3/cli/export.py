"""percell3 export — export measurements to CSV."""

from __future__ import annotations

from pathlib import Path

import click

from percell3.cli.utils import console, error_handler, open_experiment


@click.command()
@click.argument("output", type=click.Path())
@click.option(
    "-e", "--experiment", required=True, type=click.Path(exists=True),
    help="Path to the .percell experiment.",
)
@error_handler
def export(output: str, experiment: str) -> None:
    """Export measurements to CSV."""
    store = open_experiment(experiment)
    try:
        out_path = Path(output)
        store.export_csv(out_path)
        console.print(f"[green]Exported measurements to {out_path}[/green]")
    finally:
        store.close()
