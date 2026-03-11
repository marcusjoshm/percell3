"""Reusable menu system for PerCell 4 CLI.

Provides MenuItem, MenuState, Menu, and navigation helpers.
Ported from percell3.cli.menu_system with percell4 imports.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from percell4.cli.utils import console

if TYPE_CHECKING:
    from percell4.core.experiment_store import ExperimentStore


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MenuItem:
    """A single entry in a menu."""

    key: str
    label: str
    description: str
    handler: Callable[[MenuState], None] | None
    enabled: bool = True


@dataclass
class MenuState:
    """Holds state across the interactive menu session."""

    experiment_path: Path | None = None
    store: ExperimentStore | None = None
    running: bool = True

    def set_experiment(self, path: Path) -> None:
        """Open an experiment and set it as current."""
        from percell4.core.experiment_store import ExperimentStore

        if self.store:
            self.store.close()
        self.store = ExperimentStore.open(path)
        self.experiment_path = path

    def close(self) -> None:
        """Clean up resources."""
        if self.store:
            self.store.close()
            self.store = None


# ---------------------------------------------------------------------------
# Navigation exceptions
# ---------------------------------------------------------------------------


class _MenuCancel(Exception):
    """Raised when user cancels an operation (go back one level)."""


class _MenuHome(Exception):
    """Raised when user presses 'h' to return to the home menu."""


# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------


def _flush_stdin() -> None:
    """Discard any buffered stdin data."""
    import select

    try:
        while select.select([sys.stdin], [], [], 0)[0]:
            sys.stdin.read(1)
    except Exception:
        pass


def require_experiment(state: MenuState) -> ExperimentStore:
    """Get the current experiment store or raise _MenuCancel.

    Args:
        state: The current menu state.

    Returns:
        The open ExperimentStore.

    Raises:
        _MenuCancel: If no experiment is loaded.
    """
    if state.store is None:
        console.print("[yellow]No experiment selected.[/yellow]")
        console.print("[dim]Use Setup > Open experiment first.[/dim]")
        raise _MenuCancel()
    return state.store


def menu_prompt(
    prompt: str,
    *,
    choices: list[str] | None = None,
    default: str | None = None,
) -> str:
    """Prompt with universal navigation keys (h=home, b=back).

    Args:
        prompt: The text prompt to display.
        choices: Optional valid choices to validate against.
        default: Default value when user presses Enter.

    Returns:
        The user's input string.

    Raises:
        _MenuHome: When user enters 'h'.
        _MenuCancel: When user enters 'b' or on EOFError.
    """
    hint = " (h=home, b=back)"
    full_prompt = prompt + hint
    _flush_stdin()

    while True:
        try:
            raw = console.input(f"{full_prompt}: ").strip()
        except EOFError:
            raise _MenuCancel()

        if not raw and default is not None:
            return default
        if not raw:
            continue

        lower = raw.lower()
        if lower == "h":
            raise _MenuHome()
        if lower in ("b", "q"):
            raise _MenuCancel()

        if choices is not None and raw not in choices:
            valid = ", ".join(choices)
            console.print(f"[red]Invalid choice.[/red] Options: {valid}")
            continue

        return raw


# ---------------------------------------------------------------------------
# Menu class
# ---------------------------------------------------------------------------


def _print_numbered_list(items: list[str], *, page_size: int = 999) -> None:
    """Print items as a numbered list, paginating if needed."""
    show = items if len(items) <= page_size else items[:page_size]
    for i, item in enumerate(show, 1):
        console.print(f"  \\[{i}] {item}")
    if len(items) > page_size:
        console.print(f"  [dim]... and {len(items) - page_size} more[/dim]")


def numbered_select_one(
    items: list[str],
    prompt: str = "Select",
) -> str:
    """Display a numbered list and return the selected item.

    Auto-selects when only one option exists.

    Raises:
        _MenuHome / _MenuCancel via menu_prompt.
    """
    if not items:
        raise ValueError("numbered_select_one called with empty list")

    if len(items) == 1:
        console.print(f"  [dim](auto-selected: {items[0]})[/dim]")
        return items[0]

    _print_numbered_list(items)
    valid = [str(i) for i in range(1, len(items) + 1)]
    choice = menu_prompt(prompt, choices=valid)
    return items[int(choice) - 1]


def numbered_select_many(
    items: list[str],
    prompt: str = "Select (numbers, 'all', or blank=all)",
) -> list[str]:
    """Display a numbered list and return selected items.

    Supports space-separated numbers, 'all', and blank (= all).

    Raises:
        _MenuHome / _MenuCancel via menu_prompt.
    """
    if not items:
        raise ValueError("numbered_select_many called with empty list")

    _print_numbered_list(items)

    while True:
        raw = menu_prompt(prompt, default="all")

        if raw.lower() == "all":
            return list(items)

        parts = raw.split()
        try:
            indices = list({int(p) for p in parts})  # deduplicate
        except ValueError:
            console.print("[red]Enter numbers separated by spaces, or 'all'.[/red]")
            continue

        if any(i < 1 or i > len(items) for i in indices):
            console.print(f"[red]Numbers must be 1-{len(items)}.[/red]")
            continue

        if not indices:
            continue

        indices.sort()
        return [items[i - 1] for i in indices]


class Menu:
    """A reusable menu with render-prompt-dispatch loop.

    Args:
        title: Menu title (e.g. "MAIN MENU", "SETUP").
        items: Menu items including a Back item (handler=None) for sub-menus.
        state: Shared session state.
        show_banner: If True, show full ASCII banner (main menu only).
        return_home: If True, return to home after handler completes.
    """

    def __init__(
        self,
        title: str,
        items: list[MenuItem],
        state: MenuState,
        show_banner: bool = False,
        return_home: bool = False,
    ) -> None:
        self.title = title
        self.items = items
        self.state = state
        self.show_banner = show_banner
        self.return_home = return_home

    def run(self) -> None:
        """Render-prompt-dispatch loop."""
        while True:
            self._clear_screen()
            self._render_header()
            self._render_items()

            try:
                choice = self._prompt()
            except _MenuCancel:
                return

            if choice is None:
                return

            item = self._find_item(choice)
            if item is None:
                continue

            if not item.enabled:
                console.print(
                    f"\n[yellow]{item.label} is not yet available.[/yellow]"
                )
                console.print("[dim]This feature is under development.[/dim]")
                self._wait_for_enter()
                continue

            if item.handler is None:
                return

            show_gate = True
            try:
                item.handler(self.state)
            except _MenuCancel:
                show_gate = False
            except _MenuHome:
                if self.show_banner:
                    continue
                raise
            except Exception as e:
                from percell4.core.exceptions import ExperimentError

                if isinstance(e, ExperimentError):
                    console.print(f"[red]Error:[/red] {e}")
                elif isinstance(e, (KeyboardInterrupt, SystemExit)):
                    raise
                else:
                    console.print(f"[red]Internal error:[/red] {e}")

            if show_gate:
                self._wait_for_enter()
                if self.return_home:
                    raise _MenuHome()

    def _clear_screen(self) -> None:
        if console.is_terminal:
            console.clear()

    def _wait_for_enter(self) -> None:
        if console.is_terminal:
            try:
                console.input("\n[dim]Press Enter to continue...[/dim]")
            except EOFError:
                pass

    def _render_header(self) -> None:
        if self.show_banner:
            _show_header(self.state)
        else:
            if self.state.experiment_path:
                name = ""
                if self.state.store:
                    try:
                        exp = self.state.store.db.get_experiment()
                        name = exp["name"]
                    except Exception:
                        name = str(self.state.experiment_path)
                console.print(f"\nPerCell 4 | Experiment: [cyan]{name}[/cyan]")
            else:
                console.print("\nPerCell 4 | Experiment: [dim]None selected[/dim]")
            console.print(f"[bold]{self.title}[/bold]\n")

    def _render_items(self) -> None:
        for item in self.items:
            if not item.enabled:
                console.print(
                    f"  [bold white]{item.key}.[/bold white] "
                    f"[dim]{item.label}  - {item.description}  (coming soon)[/dim]"
                )
            elif item.handler is None:
                console.print(
                    f"  [bold white]{item.key}.[/bold white] [red]{item.label}[/red]"
                )
            else:
                console.print(
                    f"  [bold white]{item.key}.[/bold white] "
                    f"[bold yellow]{item.label}[/bold yellow] "
                    f"[dim]- {item.description}[/dim]"
                )

    def _prompt(self) -> str | None:
        """Prompt for user selection.

        Returns:
            The selected key, or None to exit (main menu 'q').

        Raises:
            _MenuCancel: When user presses 'b' in sub-menu prompt.
        """
        valid_keys = [item.key for item in self.items]

        if self.show_banner:
            try:
                raw = console.input("\nSelect (q=quit): ").strip()
            except EOFError:
                return None

            if not raw or raw.lower() == "q":
                return None

            if raw in valid_keys:
                return raw

            console.print(f"[red]Invalid option: {raw}[/red]")
            return ""
        else:
            return menu_prompt("Select", choices=valid_keys)

    def _find_item(self, key: str) -> MenuItem | None:
        for item in self.items:
            if item.key == key:
                return item
        return None


# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------


_BANNER_LINES = [
    "      \u25ce                                                                        ",
    "      \u2551      \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557 \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557 \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557\u2588\u2588\u2557      \u2588\u2588\u2557          ",
    "     \u2590\u2588\u258c     \u2588\u2588\u2554\u2550\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2554\u2550\u2550\u2550\u2550\u2550\u255d\u2588\u2588\u2554\u2550\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2554\u2550\u2550\u2550\u2550\u255d\u2588\u2588\u2554\u2550\u2550\u2550\u2550\u2550\u255d\u2588\u2588\u2551      \u2588\u2588\u2551          ",
    "     \u2590\u2588\u258c     \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557 \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d\u2588\u2588\u2551     \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557 \u2588\u2588\u2551      \u2588\u2588\u2551          ",
    "      \u2588      \u2588\u2588\u2554\u2550\u2550\u2550\u2550\u255d \u2588\u2588\u2554\u2550\u2550\u2550\u2550\u255d \u2588\u2588\u2554\u2550\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2551     \u2588\u2588\u2554\u2550\u2550\u2550\u2550\u255d \u2588\u2588\u2551      \u2588\u2588\u2551          ",
    "      \u25bd      \u2588\u2588\u2551      \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557\u2588\u2588\u2551   \u2588\u2588\u2551\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557    ",
    "   \u2500\u2500\u2500\u25cf\u2500\u2500\u2500   \u255a\u2550\u255d      \u255a\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u255d\u255a\u2550\u255d   \u255a\u2550\u255d\u255a\u2550\u2550\u2550\u2550\u2550\u2550\u255d\u255a\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u255d\u255a\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u255d\u255a\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u255d    ",
    "   \u2580\u2588\u2588\u2588\u2588\u2588\u2580                                                                     ",
]


def _colorize_banner_line(line: str) -> str:
    """Color a banner line: cyan microscope, green PER, magenta CELL."""
    parts = []
    for j, char in enumerate(line):
        if char == " ":
            parts.append(char)
        elif j <= 10:
            parts.append(f"[cyan]{char}[/cyan]")
        elif j <= 39:
            parts.append(f"[green]{char}[/green]")
        else:
            parts.append(f"[magenta]{char}[/magenta]")
    return "".join(parts)


def _show_header(state: MenuState) -> None:
    """Display the ASCII art banner, welcome message, and experiment context."""
    console.print()
    for line in _BANNER_LINES:
        console.print(_colorize_banner_line(line))
    console.print()
    console.print(
        "[bold]           PerCell 4.0 -- Single-Cell Microscopy Analysis           [/bold]"
    )
    console.print()
    if state.experiment_path:
        name = ""
        if state.store:
            try:
                exp = state.store.db.get_experiment()
                name = exp["name"]
            except Exception:
                name = str(state.experiment_path)
        label = name if name else str(state.experiment_path)
        console.print(f"  Experiment: [cyan]{label}[/cyan]\n")
    else:
        console.print("  Experiment: [dim]None selected[/dim]\n")
