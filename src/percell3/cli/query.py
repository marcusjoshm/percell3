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
@click.option("--bio-rep", default=None, help="Filter by biological replicate.")
@click.pass_context
@error_handler
def fovs(ctx: click.Context, fmt: str, condition: str | None, bio_rep: str | None) -> None:
    """List FOVs in the experiment."""
    store = ctx.obj["store"]
    fov_list = store.get_fovs(condition=condition, bio_rep=bio_rep)

    if not fov_list:
        console.print("[dim]No FOVs found.[/dim]")
        return

    rows = [
        {
            "name": f.name,
            "condition": f.condition,
            "bio_rep": f.bio_rep,
            "size": f"{f.width}x{f.height}" if f.width else "",
            "pixel_size_um": str(f.pixel_size_um) if f.pixel_size_um else "",
        }
        for f in fov_list
    ]
    format_output(
        rows, ["name", "condition", "bio_rep", "size", "pixel_size_um"], fmt, "FOVs",
    )


@query.command("bio-reps")
@click.option("--format", "fmt", type=click.Choice(["table", "csv", "json"]),
              default="table", help="Output format.")
@click.pass_context
@error_handler
def bio_reps(ctx: click.Context, fmt: str) -> None:
    """List biological replicates in the experiment."""
    store = ctx.obj["store"]
    rep_list = store.get_bio_reps()

    if not rep_list:
        console.print("[dim]No biological replicates found.[/dim]")
        return

    rows = [{"name": r} for r in rep_list]
    format_output(rows, ["name"], fmt, "Biological Replicates")


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


@query.command()
@click.option("--format", "fmt", type=click.Choice(["table", "csv", "json"]),
              default="table", help="Output format.")
@click.pass_context
@error_handler
def summary(ctx: click.Context, fmt: str) -> None:
    """Show per-FOV experiment summary (cells, measurements, particles)."""
    store = ctx.obj["store"]
    rows = store.get_experiment_summary()

    if not rows:
        console.print("[dim]No FOVs found.[/dim]")
        return

    # Format for display
    display_rows = []
    for s in rows:
        p_ch = s["particle_channels"] or ""
        p_count = s["particles"]
        if p_ch and p_count:
            particle_str = f"{p_ch} ({p_count})"
        elif p_ch:
            particle_str = p_ch
        else:
            particle_str = "-"

        display_rows.append({
            "condition": s["condition_name"],
            "bio_rep": s["bio_rep_name"],
            "fov": s["fov_name"],
            "cells": str(s["cells"]),
            "seg_model": s["seg_model"] or "-",
            "measured": s["measured_channels"] or "-",
            "masked": s["masked_channels"] or "-",
            "particles": particle_str,
        })

    columns = [
        "condition", "bio_rep", "fov", "cells", "seg_model",
        "measured", "masked", "particles",
    ]
    format_output(display_rows, columns, fmt, "Experiment Summary")


@query.command("add-bio-rep")
@click.argument("name")
@click.pass_context
@error_handler
def add_bio_rep(ctx: click.Context, name: str) -> None:
    """Add a biological replicate to the experiment."""
    store = ctx.obj["store"]
    store.add_bio_rep(name)
    console.print(f"[green]Added bio rep:[/green] {name}")
