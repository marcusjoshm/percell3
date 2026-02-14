"""Shared CLI utilities — Rich console, error handling, experiment helpers."""

from __future__ import annotations

import functools
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

if TYPE_CHECKING:
    from percell3.core import ExperimentStore

console = Console()


def open_experiment(path: str) -> ExperimentStore:
    """Open an experiment with CLI-friendly error handling.

    Args:
        path: Path to the .percell directory.

    Returns:
        An open ExperimentStore.

    Raises:
        SystemExit: With code 1 if the experiment is not found.
    """
    from percell3.core import ExperimentStore
    from percell3.core.exceptions import ExperimentNotFoundError

    try:
        return ExperimentStore.open(Path(path))
    except ExperimentNotFoundError:
        console.print(f"[red]Error:[/red] No experiment found at {path}")
        raise SystemExit(1)


def error_handler(func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator wrapping CLI commands with standard error handling.

    Catches ExperimentError (exit 1) and unexpected exceptions (exit 2).
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        from percell3.core.exceptions import ExperimentError

        try:
            return func(*args, **kwargs)
        except SystemExit:
            raise
        except ExperimentError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise SystemExit(1)
        except Exception as e:
            console.print(f"[red]Internal error:[/red] {e}")
            raise SystemExit(2)

    return wrapper


def make_progress() -> Progress:
    """Create a Rich progress bar for CLI operations."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    )
