"""Tests for percell4.cli.menu_handlers — handler modules and build_main_menu."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from percell4.cli.menu_system import Menu, MenuState, _MenuCancel


class TestBuildMainMenu:
    """Tests for the build_main_menu function."""

    def test_build_main_menu_returns_menu(self) -> None:
        """build_main_menu returns a Menu instance with show_banner=True."""
        from percell4.cli.menu_handlers import build_main_menu

        state = MenuState()
        menu = build_main_menu(state)
        assert isinstance(menu, Menu)
        assert menu.show_banner is True
        assert menu.title == "MAIN MENU"

    def test_build_main_menu_has_expected_items(self) -> None:
        """Main menu has the expected category items."""
        from percell4.cli.menu_handlers import build_main_menu

        state = MenuState()
        menu = build_main_menu(state)
        keys = [item.key for item in menu.items]
        assert "1" in keys  # Setup
        assert "2" in keys  # Import
        assert "3" in keys  # Segment
        assert "4" in keys  # Analyze
        assert "5" in keys  # Data
        assert "6" in keys  # Plugins

    def test_build_main_menu_items_have_handlers(self) -> None:
        """All main menu items have non-None handlers."""
        from percell4.cli.menu_handlers import build_main_menu

        state = MenuState()
        menu = build_main_menu(state)
        for item in menu.items:
            assert item.handler is not None, f"Item '{item.label}' has no handler"


class TestStatusHandler:
    """Tests for the status handler."""

    def test_status_handler_with_mock_store(self) -> None:
        """status_handler runs without error against a mock store."""
        from percell4.cli.menu_handlers.status import status_handler

        mock_store = MagicMock()
        mock_store.root = "/tmp/test.percell"
        mock_store.get_experiment.return_value = {
            "id": b"\x00" * 16,
            "name": "Test Experiment",
        }
        mock_store.get_channels.return_value = [
            {"id": b"\x01" * 16, "name": "DAPI"},
            {"id": b"\x02" * 16, "name": "GFP"},
        ]
        mock_store.get_fovs.return_value = [
            {"id": b"\x03" * 16, "status": "imported", "auto_name": "FOV_001"},
            {"id": b"\x04" * 16, "status": "imported", "auto_name": "FOV_002"},
            {"id": b"\x05" * 16, "status": "segmented", "auto_name": "FOV_003"},
        ]

        state = MenuState()
        state.store = mock_store

        # Should not raise
        status_handler(state)

        mock_store.get_experiment.assert_called_once()
        mock_store.get_channels.assert_called_once()
        mock_store.get_fovs.assert_called_once()

    def test_status_handler_no_fovs(self) -> None:
        """status_handler handles empty FOV list gracefully."""
        from percell4.cli.menu_handlers.status import status_handler

        mock_store = MagicMock()
        mock_store.root = "/tmp/test.percell"
        mock_store.get_experiment.return_value = {
            "id": b"\x00" * 16,
            "name": "Empty Experiment",
        }
        mock_store.get_channels.return_value = [
            {"id": b"\x01" * 16, "name": "DAPI"},
        ]
        mock_store.get_fovs.return_value = []

        state = MenuState()
        state.store = mock_store

        # Should not raise
        status_handler(state)


class TestThresholdHandler:
    """Tests for the threshold placeholder handler."""

    def test_threshold_handler_prints_warning(self) -> None:
        """threshold_handler runs without error, just prints warning."""
        from percell4.cli.menu_handlers.threshold import threshold_handler

        state = MenuState()
        state.store = MagicMock()

        # Should not raise
        threshold_handler(state)

    def test_threshold_handler_requires_experiment(self) -> None:
        """threshold_handler raises _MenuCancel without a store."""
        from percell4.cli.menu_handlers.threshold import threshold_handler

        state = MenuState()
        with pytest.raises(_MenuCancel):
            threshold_handler(state)


class TestMergeHandler:
    """Tests for the merge handler."""

    def test_merge_handler_requires_experiment(self) -> None:
        """merge_handler raises _MenuCancel without a store."""
        from percell4.cli.menu_handlers.merge import merge_handler

        state = MenuState()
        with pytest.raises(_MenuCancel):
            merge_handler(state)


class TestExportHandlers:
    """Tests for the export handlers."""

    def test_export_csv_requires_experiment(self) -> None:
        """export_csv_handler raises _MenuCancel without a store."""
        from percell4.cli.menu_handlers.export import export_csv_handler

        state = MenuState()
        with pytest.raises(_MenuCancel):
            export_csv_handler(state)

    def test_export_prism_requires_experiment(self) -> None:
        """export_prism_handler raises _MenuCancel without a store."""
        from percell4.cli.menu_handlers.export import export_prism_handler

        state = MenuState()
        with pytest.raises(_MenuCancel):
            export_prism_handler(state)

    def test_export_compat_requires_experiment(self) -> None:
        """export_compat_handler raises _MenuCancel without a store."""
        from percell4.cli.menu_handlers.export import export_compat_handler

        state = MenuState()
        with pytest.raises(_MenuCancel):
            export_compat_handler(state)
