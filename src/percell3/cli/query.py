"""percell3 query — inspect experiment data."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

import click
from rich.table import Table

from percell3.cli.utils import console, error_handler, open_experiment


def format_output(
    rows: list[dict[str, Any]],
    columns: list[str],
    fmt: str,
    title: str,
) -> None:
    """Render rows in the requested format (table, csv, or json).

    Args:
        rows: List of dicts, each with keys matching columns.
        columns: Column names (display order).
        fmt: One of "table", "csv", "json".
        title: Title for table output.
    """
    if fmt == "table":
        table = Table(show_header=True, title=title)
        for col in columns:
            if col == columns[0]:
                table.add_column(col, style="bold")
            else:
                table.add_column(col)
        for row in rows:
            table.add_row(*(str(row.get(c, "")) for c in columns))
        console.print(table)
    elif fmt == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([row.get(c, "") for c in columns])
        # Print without trailing newline from csv module
        console.print(buf.getvalue().rstrip())
    elif fmt == "json":
        console.print(json.dumps(rows, indent=2))


@click.group()
@click.option(
    "-e", "--experiment", required=True, type=click.Path(exists=True),
    help="Path to the .percell experiment.",
)
@click.pass_context
@error_handler
def query(ctx: click.Context, experiment: str) -> None:
    """Query experiment data."""
    ctx.ensure_object(dict)
    ctx.obj["store"] = open_experiment(experiment)


@query.result_callback()
@click.pass_context
def cleanup(ctx: click.Context, *args: object, **kwargs: object) -> None:
    """Close the store after any query subcommand completes."""
    store = ctx.obj.get("store")
    if store:
        store.close()


@query.command()
@click.option("--format", "fmt", type=click.Choice(["table", "csv", "json"]),
              default="table", help="Output format.")
@click.pass_context
@error_handler
def channels(ctx: click.Context, fmt: str) -> None:
    """List channels in the experiment."""
    store = ctx.obj["store"]
    ch_list = store.get_channels()

    if not ch_list:
        console.print("[dim]No channels found.[/dim]")
        return

    rows = [{"name": ch.name, "role": ch.role or "", "color": ch.color or ""}
            for ch in ch_list]
    format_output(rows, ["name", "role", "color"], fmt, "Channels")


@query.command()
@click.option("--format", "fmt", type=click.Choice(["table", "csv", "json"]),
              default="table", help="Output format.")
@click.option("--condition", default=None, help="Filter by condition.")
@click.pass_context
@error_handler
def regions(ctx: click.Context, fmt: str, condition: str | None) -> None:
    """List regions in the experiment."""
    store = ctx.obj["store"]
    region_list = store.get_regions(condition=condition)

    if not region_list:
        console.print("[dim]No regions found.[/dim]")
        return

    rows = [
        {
            "name": r.name,
            "condition": r.condition,
            "size": f"{r.width}x{r.height}" if r.width else "",
            "pixel_size_um": str(r.pixel_size_um) if r.pixel_size_um else "",
        }
        for r in region_list
    ]
    format_output(rows, ["name", "condition", "size", "pixel_size_um"], fmt, "Regions")


@query.command()
@click.option("--format", "fmt", type=click.Choice(["table", "csv", "json"]),
              default="table", help="Output format.")
@click.pass_context
@error_handler
def conditions(ctx: click.Context, fmt: str) -> None:
    """List conditions in the experiment."""
    store = ctx.obj["store"]
    cond_list = store.get_conditions()

    if not cond_list:
        console.print("[dim]No conditions found.[/dim]")
        return

    rows = [{"name": c} for c in cond_list]
    format_output(rows, ["name"], fmt, "Conditions")
