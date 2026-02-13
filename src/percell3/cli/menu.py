"""Interactive menu for PerCell 3 CLI."""

from __future__ import annotations

from percell3.cli.utils import console


def run_interactive_menu() -> None:
    """Run the interactive menu loop.

    Launched when `percell3` is run with no arguments.
    """
    console.print("\n[bold]PerCell 3[/bold] — Single-Cell Microscopy Analysis\n")
    console.print("[dim]Interactive menu not yet implemented.[/dim]")
    console.print("Use [bold]percell3 --help[/bold] to see available commands.\n")
