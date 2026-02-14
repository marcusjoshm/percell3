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
@click.option(
    "--overwrite", is_flag=True,
    help="Overwrite output file if it exists.",
)
@click.option(
    "--channels", default=None,
    help="Comma-separated list of channels to export.",
)
@click.option(
    "--metrics", default=None,
    help="Comma-separated list of metrics to export.",
)
@error_handler
def export(
    output: str,
    experiment: str,
    overwrite: bool,
    channels: str | None,
    metrics: str | None,
) -> None:
    """Export measurements to CSV."""
    store = open_experiment(experiment)
    try:
        out_path = Path(output).expanduser()

        # Check overwrite
        if out_path.exists() and not overwrite:
            console.print(
                f"[red]Error:[/red] Output file already exists: {out_path}\n"
                "Use --overwrite to replace it."
            )
            raise SystemExit(1)

        # Parse filter lists
        ch_list = [c.strip() for c in channels.split(",")] if channels else None
        met_list = [m.strip() for m in metrics.split(",")] if metrics else None

        with console.status("[bold blue]Exporting measurements..."):
            store.export_csv(out_path, channels=ch_list, metrics=met_list)

        console.print(f"[green]Exported measurements to {out_path}[/green]")
    finally:
        store.close()
