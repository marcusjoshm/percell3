"""percell3 query — inspect experiment data."""

from __future__ import annotations

import json

import click
from rich.table import Table

from percell3.cli.utils import console, error_handler, open_experiment


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

    if fmt == "table":
        table = Table(show_header=True, title="Channels")
        table.add_column("Name", style="bold")
        table.add_column("Role")
        table.add_column("Color")
        for ch in ch_list:
            table.add_row(ch.name, ch.role or "", ch.color or "")
        console.print(table)
    elif fmt == "csv":
        console.print("name,role,color")
        for ch in ch_list:
            console.print(f"{ch.name},{ch.role or ''},{ch.color or ''}")
    elif fmt == "json":
        data = [{"name": ch.name, "role": ch.role, "color": ch.color}
                for ch in ch_list]
        console.print(json.dumps(data, indent=2))


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

    if fmt == "table":
        table = Table(show_header=True, title="Regions")
        table.add_column("Name", style="bold")
        table.add_column("Condition")
        table.add_column("Size")
        table.add_column("Pixel Size (\u00b5m)")
        for r in region_list:
            size = f"{r.width}x{r.height}" if r.width else ""
            ps = f"{r.pixel_size_um}" if r.pixel_size_um else ""
            table.add_row(r.name, r.condition, size, ps)
        console.print(table)
    elif fmt == "csv":
        console.print("name,condition,width,height,pixel_size_um")
        for r in region_list:
            console.print(
                f"{r.name},{r.condition},{r.width or ''},{r.height or ''},"
                f"{r.pixel_size_um or ''}"
            )
    elif fmt == "json":
        data = [
            {"name": r.name, "condition": r.condition,
             "width": r.width, "height": r.height,
             "pixel_size_um": r.pixel_size_um}
            for r in region_list
        ]
        console.print(json.dumps(data, indent=2))


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

    if fmt == "table":
        table = Table(show_header=True, title="Conditions")
        table.add_column("Name", style="bold")
        for c in cond_list:
            table.add_row(c)
        console.print(table)
    elif fmt == "csv":
        console.print("name")
        for c in cond_list:
            console.print(c)
    elif fmt == "json":
        console.print(json.dumps(cond_list, indent=2))
