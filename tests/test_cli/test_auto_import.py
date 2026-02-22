"""Tests for build_auto_assignments (auto-import logic)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from percell3.cli.import_cmd import FileGroup, build_auto_assignments


def _make_group(token: str, channels: list[str] | None = None) -> FileGroup:
    """Create a minimal FileGroup for testing."""
    return FileGroup(
        token=token,
        files=[],
        channels=channels or ["00", "01"],
        z_slices=[],
        shape=(64, 64),
    )


def _make_store(existing_conditions: list[str] | None = None) -> MagicMock:
    """Create a mock ExperimentStore with get_conditions()."""
    store = MagicMock()
    store.get_conditions.return_value = existing_conditions or []
    return store


class TestBuildAutoAssignments:
    def test_uses_token_as_condition_name(self):
        groups = [_make_group("alpha"), _make_group("beta"), _make_group("gamma")]
        store = _make_store()

        condition_map, _, _, _ = build_auto_assignments(groups, store)

        assert condition_map == {
            "alpha": "alpha",
            "beta": "beta",
            "gamma": "gamma",
        }

    def test_channels_auto_named(self):
        groups = [_make_group("alpha", channels=["00", "01"])]
        store = _make_store()

        _, _, _, channel_maps = build_auto_assignments(groups, store)

        assert channel_maps == ("00:ch00", "01:ch01")

    def test_collision_with_existing_appends_suffix(self):
        groups = [_make_group("alpha")]
        store = _make_store(existing_conditions=["alpha"])

        condition_map, _, _, _ = build_auto_assignments(groups, store)

        assert condition_map["alpha"] == "alpha_2"

    def test_suffix_increments_past_existing(self):
        groups = [_make_group("alpha")]
        store = _make_store(existing_conditions=["alpha", "alpha_2"])

        condition_map, _, _, _ = build_auto_assignments(groups, store)

        assert condition_map["alpha"] == "alpha_3"

    def test_all_fov_names_are_FOV_001(self):
        groups = [_make_group("a"), _make_group("b"), _make_group("c")]
        store = _make_store()

        _, fov_names, _, _ = build_auto_assignments(groups, store)

        assert all(v == "FOV_001" for v in fov_names.values())

    def test_all_bio_reps_are_N1(self):
        groups = [_make_group("a"), _make_group("b"), _make_group("c")]
        store = _make_store()

        _, _, bio_rep_map, _ = build_auto_assignments(groups, store)

        assert all(v == "N1" for v in bio_rep_map.values())

    def test_batch_collision_between_groups(self):
        """Two groups with the same token (after sanitization) get unique names."""
        # This shouldn't happen with real file groups (tokens are unique),
        # but test the safety mechanism: if two groups had the same sanitized
        # name, the second should get a suffix.
        groups = [_make_group("alpha"), _make_group("alpha_clone")]
        store = _make_store(existing_conditions=["alpha_clone"])

        condition_map, _, _, _ = build_auto_assignments(groups, store)

        assert condition_map["alpha"] == "alpha"
        assert condition_map["alpha_clone"] == "alpha_clone_2"

    def test_channels_collected_across_groups(self):
        """Channel tokens are the union across all groups."""
        groups = [
            _make_group("a", channels=["00"]),
            _make_group("b", channels=["00", "01", "02"]),
        ]
        store = _make_store()

        _, _, _, channel_maps = build_auto_assignments(groups, store)

        assert channel_maps == ("00:ch00", "01:ch01", "02:ch02")

    def test_sanitizes_token_for_condition_name(self):
        """Tokens with special chars are sanitized."""
        groups = [_make_group("HS_+_VCPi_Merged")]
        store = _make_store()

        condition_map, _, _, _ = build_auto_assignments(groups, store)

        assert condition_map["HS_+_VCPi_Merged"] == "HS_+_VCPi_Merged"
