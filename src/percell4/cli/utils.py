"""Shared CLI utilities — Rich console, progress bars, error formatting."""

from __future__ import annotations

import sys
from pathlib import Path

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)

console = Console()


def make_progress() -> Progress:
    """Create a Rich progress bar for CLI operations."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    )


def format_uuid_short(b: bytes) -> str:
    """Short display: first 8 hex chars of a UUID.

    Args:
        b: A 16-byte UUID value.

    Returns:
        First 8 characters of the canonical UUID string.
    """
    from percell4.core.db_types import uuid_to_str

    return uuid_to_str(b)[:8]


def print_error(msg: str) -> None:
    """Print an error message in bold red."""
    console.print(f"[bold red]Error:[/] {msg}")


def print_success(msg: str) -> None:
    """Print a success message with green checkmark."""
    console.print(f"[bold green]OK:[/] {msg}")


def print_warning(msg: str) -> None:
    """Print a warning message in yellow."""
    console.print(f"[bold yellow]Warning:[/] {msg}")


def is_interactive() -> bool:
    """Return True if stdin is connected to a TTY."""
    return sys.stdin.isatty()


FOV_STATUS_EXPLANATIONS: dict[str, str] = {
    "pending": "Import in progress",
    "imported": "Ready for segmentation",
    "segmented": "Ready for measurement",
    "measured": "Ready for analysis",
    "analyzing": "Analysis in progress",
    "qc_pending": "Awaiting quality check",
    "qc_done": "Quality check complete",
    "stale": "Upstream data changed -- re-run analysis to update",
    "deleting": "Deletion in progress",
    "deleted": "Removed",
    "error": "Error occurred during processing",
}
