"""Reusable menu system for PerCell 3 CLI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from percell3.cli.utils import console

if TYPE_CHECKING:
    from percell3.cli.menu import MenuState


@dataclass(frozen=True)
class MenuItem:
    """A single entry in a menu."""

    key: str
    label: str
    description: str
    handler: Callable[[MenuState], None] | None
    enabled: bool = True


class Menu:
    """A reusable menu with render-prompt-dispatch loop.

    Args:
        title: Menu title (e.g. "MAIN MENU", "SETUP").
        items: Menu items including a Back item (handler=None) for sub-menus.
        state: Shared session state.
        show_banner: If True, show full ASCII banner (main menu only).
        return_home: If True, return to home menu after a handler completes
            successfully (instead of looping back to this sub-menu).
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
        """Render-prompt-dispatch loop.

        Clears screen, renders header + items, prompts for selection,
        dispatches to handler, shows "Press Enter" gate, and loops.
        """
        from percell3.cli.menu import _MenuCancel, _MenuHome, _show_header

        while True:
            self._clear_screen()
            self._render_header()
            self._render_items()

            try:
                choice = self._prompt()
            except _MenuCancel:
                return

            if choice is None:
                # 'q' on main menu → exit
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
                # "Back" item
                return

            show_gate = True
            try:
                item.handler(self.state)
            except _MenuCancel:
                show_gate = False  # cancelled — nothing to show
            except _MenuHome:
                if self.show_banner:
                    continue  # main menu: restart loop
                raise  # sub-menu: propagate up
            except Exception as e:
                from percell3.core.exceptions import ExperimentError

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
        from percell3.cli.menu import _show_header

        if self.show_banner:
            _show_header(self.state)
        else:
            # Compact header for sub-menus
            if self.state.experiment_path:
                name = self.state.store.name if self.state.store else ""
                console.print(f"\nPerCell 3 | Experiment: [cyan]{name}[/cyan]")
            else:
                console.print("\nPerCell 3 | Experiment: [dim]None selected[/dim]")
            console.print(f"[bold]{self.title}[/bold]\n")

    def _render_items(self) -> None:
        for item in self.items:
            if not item.enabled:
                console.print(
                    f"  [bold white]{item.key}.[/bold white] "
                    f"[dim]{item.label}  - {item.description}  (coming soon)[/dim]"
                )
            elif item.handler is None:
                # "Back" item
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
        from percell3.cli.menu import _MenuCancel, menu_prompt

        valid_keys = [item.key for item in self.items]

        if self.show_banner:
            # Main menu: simple prompt, 'q' exits
            try:
                raw = console.input("\nSelect (q=quit): ").strip()
            except EOFError:
                return None

            if not raw or raw.lower() == "q":
                return None

            if raw in valid_keys:
                return raw

            console.print(f"[red]Invalid option: {raw}[/red]")
            return ""  # empty string → loop continues via _find_item returning None
        else:
            # Sub-menu: use menu_prompt with h/b navigation
            return menu_prompt("Select", choices=valid_keys)

    def _find_item(self, key: str) -> MenuItem | None:
        for item in self.items:
            if item.key == key:
                return item
        return None
