"""percell3 export-prism — export measurements as Prism-ready CSV files."""

from __future__ import annotations

from pathlib import Path

import click

from percell3.cli.utils import console, error_handler, open_experiment


@click.command("export-prism")
@click.argument("output", type=click.Path())
@click.option(
    "-e", "--experiment", required=True, type=click.Path(exists=True),
    help="Path to the .percell experiment.",
)
@click.option(
    "--overwrite", is_flag=True,
    help="Overwrite output directory if it exists and is non-empty.",
)
@click.option(
    "--channels", default=None,
    help="Comma-separated list of channels to export.",
)
@click.option(
    "--metrics", default=None,
    help="Comma-separated list of metrics to export.",
)
@click.option(
    "--scope", default="whole_cell",
    type=click.Choice(["whole_cell", "mask_inside", "mask_outside"]),
    help="Measurement scope to export.",
)
@error_handler
def export_prism(
    output: str,
    experiment: str,
    overwrite: bool,
    channels: str | None,
    metrics: str | None,
    scope: str,
) -> None:
    """Export measurements as Prism-ready CSV files.

    Creates a directory of CSV files organized by channel and metric.
    Each CSV has one column per condition+bio-rep combination.
    """
    store = open_experiment(experiment)
    try:
        out_dir = Path(output).expanduser()

        # Reject if output is an existing file
        if out_dir.is_file():
            console.print(
                f"[red]Error:[/red] Output path is an existing file: {out_dir}\n"
                "Provide a directory path."
            )
            raise SystemExit(1)

        # Check parent directory exists
        if not out_dir.parent.exists():
            console.print(
                f"[red]Error:[/red] Parent directory does not exist: {out_dir.parent}"
            )
            raise SystemExit(1)

        # Check overwrite if directory exists and is non-empty
        if out_dir.exists() and any(out_dir.iterdir()) and not overwrite:
            console.print(
                f"[red]Error:[/red] Output directory is not empty: {out_dir}\n"
                "Use --overwrite to replace contents."
            )
            raise SystemExit(1)

        # Parse filter lists
        ch_list = [c.strip() for c in channels.split(",")] if channels else None
        met_list = [m.strip() for m in metrics.split(",")] if metrics else None

        with console.status("[bold blue]Exporting Prism-format CSVs..."):
            result = store.export_prism_csv(
                out_dir, channels=ch_list, metrics=met_list, scope=scope,
            )

        if result["files_written"] == 0:
            console.print("[yellow]No measurements found to export.[/yellow]")
        else:
            console.print(
                f"[green]Prism export complete![/green]\n"
                f"  Directory: {out_dir}\n"
                f"  Channels: {result['channels_exported']}\n"
                f"  Files written: {result['files_written']}"
            )
    finally:
        store.close()
