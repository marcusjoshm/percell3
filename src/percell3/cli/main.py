"""PerCell 3 CLI — top-level Click group and interactive menu."""

from __future__ import annotations

import click


@click.group(invoke_without_command=True)
@click.version_option(package_name="percell3")
@click.option("--verbose", "-v", is_flag=True, help="Show full tracebacks on errors.")
@click.pass_context
def cli(ctx: click.Context, verbose: bool) -> None:
    """PerCell 3 — Single-Cell Microscopy Analysis."""
    from percell3.cli import utils

    utils.verbose = verbose

    if ctx.invoked_subcommand is None:
        from percell3.cli.menu import run_interactive_menu

        run_interactive_menu()


def _register_commands() -> None:
    """Register all subcommands — imports deferred to avoid loading heavy deps at startup."""
    from percell3.cli.create import create
    from percell3.cli.export import export
    from percell3.cli.import_cmd import import_cmd
    from percell3.cli.query import query
    from percell3.cli.segment import segment
    from percell3.cli.stubs import measure, threshold
    from percell3.cli.workflow import workflow

    cli.add_command(create)
    cli.add_command(export)
    cli.add_command(import_cmd)
    cli.add_command(measure)
    cli.add_command(query)
    cli.add_command(segment)
    cli.add_command(threshold)
    cli.add_command(workflow)


_register_commands()
