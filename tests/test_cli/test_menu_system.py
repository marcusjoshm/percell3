"""Tests for percell3 Menu system (menu_system.py)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from percell3.cli.menu import MenuState, _MenuCancel, _MenuHome
from percell3.cli.menu_system import Menu, MenuItem
from percell3.cli.utils import console


@pytest.fixture
def state():
    """Minimal MenuState for testing."""
    return MenuState()


class TestMenuDispatch:
    def test_dispatches_to_correct_handler(self, state):
        handler = MagicMock()
        items = [
            MenuItem("1", "Action", "Do something", handler),
            MenuItem("2", "Back", "", None),
        ]
        # Input: select "1", then press Enter for gate, then select "2" (Back)
        with patch.object(console, "input", side_effect=["1", "", "2"]):
            Menu("TEST", items, state).run()
        handler.assert_called_once_with(state)

    def test_back_item_returns(self, state):
        handler = MagicMock()
        items = [
            MenuItem("1", "Action", "Do something", handler),
            MenuItem("2", "Back", "", None),
        ]
        # Select "2" (Back) — should return without calling handler
        with patch.object(console, "input", return_value="2"):
            Menu("TEST", items, state).run()
        handler.assert_not_called()

    def test_b_key_returns_from_sub_menu(self, state):
        handler = MagicMock()
        items = [
            MenuItem("1", "Action", "Do something", handler),
            MenuItem("2", "Back", "", None),
        ]
        # Press 'b' — menu_prompt raises _MenuCancel, Menu.run() returns
        with patch.object(console, "input", return_value="b"):
            Menu("TEST", items, state).run()
        handler.assert_not_called()

    def test_h_key_propagates_menu_home(self, state):
        items = [
            MenuItem("1", "Action", "Do something", lambda s: None),
            MenuItem("2", "Back", "", None),
        ]
        # Press 'h' — menu_prompt raises _MenuHome, Menu.run() should propagate
        with patch.object(console, "input", return_value="h"):
            with pytest.raises(_MenuHome):
                Menu("TEST", items, state).run()


class TestMenuDisabledItems:
    def test_disabled_item_shows_message_and_loops(self, state):
        items = [
            MenuItem("1", "Coming", "Not ready yet", lambda s: None, enabled=False),
            MenuItem("2", "Back", "", None),
        ]
        # Select "1" (disabled) → Enter for gate → "2" (Back)
        with patch.object(console, "input", side_effect=["1", "", "2"]):
            Menu("TEST", items, state).run()


class TestMenuErrorHandling:
    def test_handler_error_caught(self, state):
        def bad_handler(s):
            raise RuntimeError("boom")

        items = [
            MenuItem("1", "Bad", "Will crash", bad_handler),
            MenuItem("2", "Back", "", None),
        ]
        # Select "1" → error caught → Enter for gate → "2" (Back)
        with patch.object(console, "input", side_effect=["1", "", "2"]):
            Menu("TEST", items, state).run()

    def test_menu_cancel_in_handler_stays_in_menu(self, state):
        def cancel_handler(s):
            raise _MenuCancel()

        items = [
            MenuItem("1", "Cancel", "Will cancel", cancel_handler),
            MenuItem("2", "Back", "", None),
        ]
        # Select "1" → handler raises _MenuCancel → Enter for gate → "2" (Back)
        with patch.object(console, "input", side_effect=["1", "", "2"]):
            Menu("TEST", items, state).run()

    def test_menu_home_in_handler_propagates(self, state):
        def home_handler(s):
            raise _MenuHome()

        items = [
            MenuItem("1", "Home", "Will go home", home_handler),
            MenuItem("2", "Back", "", None),
        ]
        # Select "1" → handler raises _MenuHome → should propagate
        with patch.object(console, "input", side_effect=["1"]):
            with pytest.raises(_MenuHome):
                Menu("TEST", items, state).run()


class TestMenuTerminalBehavior:
    def test_clear_screen_skipped_when_not_terminal(self, state):
        items = [MenuItem("1", "Back", "", None)]
        # console.is_terminal is False in test environment
        with patch.object(console, "input", return_value="1"):
            Menu("TEST", items, state).run()
        # No crash = screen clear was skipped

    def test_wait_for_enter_skipped_when_not_terminal(self, state):
        handler = MagicMock()
        items = [
            MenuItem("1", "Action", "Do something", handler),
            MenuItem("2", "Back", "", None),
        ]
        # In non-terminal mode, _wait_for_enter should be skipped
        # so we only need "1" then "2" (no Enter for gate)
        with patch.object(console, "input", side_effect=["1", "2"]):
            Menu("TEST", items, state).run()
        handler.assert_called_once()


class TestMainMenuPrompt:
    def test_q_exits_main_menu(self, state):
        items = [
            MenuItem("1", "Action", "Do something", lambda s: None),
        ]
        # Main menu uses show_banner=True, 'q' exits
        with patch.object(console, "input", return_value="q"):
            Menu("MAIN MENU", items, state, show_banner=True).run()

    def test_empty_input_exits_main_menu(self, state):
        items = [
            MenuItem("1", "Action", "Do something", lambda s: None),
        ]
        # Main menu: empty input → treated as quit
        with patch.object(console, "input", return_value=""):
            Menu("MAIN MENU", items, state, show_banner=True).run()

    def test_invalid_input_shows_error_and_loops(self, state):
        items = [
            MenuItem("1", "Action", "Do something", lambda s: None),
        ]
        # Main menu: "z" → invalid, "q" → quit
        with patch.object(console, "input", side_effect=["z", "q"]):
            Menu("MAIN MENU", items, state, show_banner=True).run()
