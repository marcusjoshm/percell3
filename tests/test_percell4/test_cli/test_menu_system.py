"""Tests for percell4.cli.menu_system — Menu framework and navigation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from percell4.cli.menu_system import (
    Menu,
    MenuItem,
    MenuState,
    _MenuCancel,
    _MenuHome,
    require_experiment,
)


class TestMenuItem:
    """Tests for the MenuItem frozen dataclass."""

    def test_menu_item_creation(self) -> None:
        """MenuItem stores key, label, description, handler, and enabled."""
        handler = MagicMock()
        item = MenuItem(
            key="1",
            label="Test",
            description="A test item",
            handler=handler,
            enabled=True,
        )
        assert item.key == "1"
        assert item.label == "Test"
        assert item.description == "A test item"
        assert item.handler is handler
        assert item.enabled is True

    def test_menu_item_defaults(self) -> None:
        """MenuItem defaults enabled to True."""
        item = MenuItem(key="x", label="X", description="", handler=None)
        assert item.enabled is True

    def test_menu_item_frozen(self) -> None:
        """MenuItem is frozen — cannot assign attributes."""
        item = MenuItem(key="1", label="A", description="B", handler=None)
        with pytest.raises(AttributeError):
            item.key = "2"  # type: ignore[misc]


class TestMenuCancelException:
    """Tests for _MenuCancel exception."""

    def test_menu_cancel_exception(self) -> None:
        """_MenuCancel can be raised and caught."""
        with pytest.raises(_MenuCancel):
            raise _MenuCancel()


class TestMenuHomeException:
    """Tests for _MenuHome exception."""

    def test_menu_home_exception(self) -> None:
        """_MenuHome can be raised and caught."""
        with pytest.raises(_MenuHome):
            raise _MenuHome()


class TestMenuState:
    """Tests for the MenuState dataclass."""

    def test_menu_state_creation(self) -> None:
        """MenuState defaults to no experiment and running."""
        state = MenuState()
        assert state.experiment_path is None
        assert state.store is None
        assert state.running is True

    def test_menu_state_with_path(self) -> None:
        """MenuState accepts an experiment_path at creation."""
        state = MenuState(experiment_path=Path("/tmp/test.percell"))
        assert state.experiment_path == Path("/tmp/test.percell")
        assert state.store is None

    def test_close_without_store(self) -> None:
        """Closing a state with no store is a no-op."""
        state = MenuState()
        state.close()
        assert state.store is None

    def test_close_with_mock_store(self) -> None:
        """Closing a state with a mock store calls store.close()."""
        state = MenuState()
        mock_store = MagicMock()
        state.store = mock_store
        state.close()
        mock_store.close.assert_called_once()
        assert state.store is None


class TestRequireExperiment:
    """Tests for the require_experiment() helper."""

    def test_require_experiment_raises_without_store(self) -> None:
        """require_experiment raises _MenuCancel when no store is loaded."""
        state = MenuState()
        with pytest.raises(_MenuCancel):
            require_experiment(state)

    def test_require_experiment_returns_store(self) -> None:
        """require_experiment returns the store when one is loaded."""
        state = MenuState()
        mock_store = MagicMock()
        state.store = mock_store
        result = require_experiment(state)
        assert result is mock_store


class TestMenu:
    """Tests for the Menu class."""

    def test_menu_creation(self) -> None:
        """Menu stores title, items, state, and flags."""
        state = MenuState()
        items = [MenuItem("1", "Test", "Desc", None)]
        menu = Menu("TEST", items, state, show_banner=False, return_home=True)
        assert menu.title == "TEST"
        assert menu.items == items
        assert menu.state is state
        assert menu.show_banner is False
        assert menu.return_home is True

    def test_find_item(self) -> None:
        """Menu._find_item returns the item with matching key."""
        state = MenuState()
        handler = MagicMock()
        items = [
            MenuItem("1", "First", "First item", handler),
            MenuItem("2", "Second", "Second item", None),
        ]
        menu = Menu("TEST", items, state)
        assert menu._find_item("1") is items[0]
        assert menu._find_item("2") is items[1]
        assert menu._find_item("3") is None
