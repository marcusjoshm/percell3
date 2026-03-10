"""Tests for FOV browser widget data logic (no Qt required)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from percell4.core.db_types import new_uuid


def _make_mock_store(fov_count: int = 3) -> MagicMock:
    """Create a mock ExperimentStore with fov_count FOVs."""
    store = MagicMock()

    exp_id = new_uuid()
    store.db.get_experiment.return_value = {"id": exp_id, "name": "Test Exp"}

    fovs = []
    for i in range(fov_count):
        fov_id = new_uuid()
        fovs.append({
            "id": fov_id,
            "auto_name": f"fov_{i}",
            "status": ["imported", "segmented", "measured"][i % 3],
            "condition_id": None,
            "pixel_size_um": 0.325,
            "zarr_path": f"zarr/images/{i}",
        })
    store.db.get_fovs.return_value = fovs

    channels = [
        {"id": new_uuid(), "name": "DAPI", "color": None},
        {"id": new_uuid(), "name": "GFP", "color": None},
    ]
    store.db.get_channels.return_value = channels
    store.db.get_conditions.return_value = []

    return store


def test_get_fov_list_data_returns_correct_count():
    """get_fov_list_data should return all non-deleted FOVs."""
    from percell4.viewer.fov_browser_widget import get_fov_list_data

    store = _make_mock_store(3)
    data = get_fov_list_data(store)
    assert len(data) == 3


def test_get_fov_list_data_excludes_deleted():
    """Deleted FOVs should be excluded from the list."""
    from percell4.viewer.fov_browser_widget import get_fov_list_data

    store = _make_mock_store(3)
    fovs = store.db.get_fovs.return_value
    fovs[2]["status"] = "deleted"

    data = get_fov_list_data(store)
    assert len(data) == 2


def test_get_fov_list_data_structure():
    """Each item should have expected keys."""
    from percell4.viewer.fov_browser_widget import get_fov_list_data

    store = _make_mock_store(1)
    data = get_fov_list_data(store)
    assert len(data) == 1

    item = data[0]
    assert "id" in item
    assert "auto_name" in item
    assert "status" in item
    assert "condition_name" in item
    assert "channel_count" in item
    assert item["channel_count"] == 2


def test_get_fov_list_data_empty_experiment():
    """Should return empty list for experiment with no FOVs."""
    from percell4.viewer.fov_browser_widget import get_fov_list_data

    store = _make_mock_store(0)
    data = get_fov_list_data(store)
    assert data == []


def test_status_colors_mapping():
    """Verify all known statuses have color entries."""
    from percell4.viewer.fov_browser_widget import _STATUS_COLORS

    expected_statuses = [
        "measured", "segmented", "imported", "pending",
        "error", "stale", "deleted",
    ]
    for status in expected_statuses:
        assert status in _STATUS_COLORS, f"Missing color for status: {status}"
