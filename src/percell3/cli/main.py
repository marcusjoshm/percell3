"""PerCell 3 CLI — top-level Click group and interactive menu."""

from __future__ import annotations

import click

from percell3.cli.create import create
from percell3.cli.export import export
from percell3.cli.import_cmd import import_cmd
from percell3.cli.query import query


@click.group(invoke_without_command=True)
@click.version_option(package_name="percell3")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """PerCell 3 — Single-Cell Microscopy Analysis."""
    if ctx.invoked_subcommand is None:
        from percell3.cli.menu import run_interactive_menu

        run_interactive_menu()


# Register commands
cli.add_command(create)
cli.add_command(export)
cli.add_command(import_cmd)
cli.add_command(query)
