"""Stub commands for modules not yet implemented."""

from __future__ import annotations

import click

from percell3.cli.utils import console


def _coming_soon(name: str, description: str) -> click.Command:
    """Create a Click command that prints 'coming soon'."""

    @click.command(name, help=f"{description} (coming soon)")
    def stub() -> None:
        console.print(f"\n[yellow]{name.title()} is not yet available.[/yellow]")
        console.print("[dim]This feature is under development.[/dim]\n")

    return stub


measure = _coming_soon("measure", "Measure channel intensities")
threshold = _coming_soon("threshold", "Apply intensity thresholds")
