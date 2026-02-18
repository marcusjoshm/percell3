"""Tests for percell3 interactive menu import flow."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
import tifffile

from percell3.cli.import_cmd import FileGroup, build_file_groups, next_fov_number, show_file_group_table
from percell3.cli.menu import (
    MenuState,
    _MenuCancel,
    _parse_group_selection,
    _prompt_bio_rep_for_assignment,
    _prompt_condition_for_assignment,
)
from percell3.cli.utils import console
from percell3.core import ExperimentStore
from percell3.io import FileScanner
from percell3.io.models import DiscoveredFile


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def multi_fov_tiff_dir(tmp_path: Path) -> Path:
    """Create TIFFs with 3 FOV groups, 2 channels, and different shapes."""
    d = tmp_path / "multi_fov"
    d.mkdir()
    for fov, shape in [("alpha", (64, 64)), ("beta", (128, 128)), ("gamma", (32, 32))]:
        for ch in (0, 1):
            data = np.random.randint(0, 65535, shape, dtype=np.uint16)
            tifffile.imwrite(str(d / f"{fov}_ch{ch:02d}.tif"), data)
    return d


@pytest.fixture
def single_fov_tiff_dir(tmp_path: Path) -> Path:
    """Create TIFFs with 1 FOV group, 2 channels."""
    d = tmp_path / "single_fov"
    d.mkdir()
    for ch in (0, 1):
        data = np.random.randint(0, 65535, (64, 64), dtype=np.uint16)
        tifffile.imwrite(str(d / f"sample_ch{ch:02d}.tif"), data)
    return d


# ---------------------------------------------------------------------------
# build_file_groups tests
# ---------------------------------------------------------------------------


class TestBuildFileGroups:
    def test_groups_by_fov_token(self, multi_fov_tiff_dir: Path):
        scanner = FileScanner()
        result = scanner.scan(multi_fov_tiff_dir)
        groups = build_file_groups(result)

        assert len(groups) == 3
        tokens = [g.token for g in groups]
        assert tokens == ["alpha", "beta", "gamma"]

    def test_group_has_correct_channels(self, multi_fov_tiff_dir: Path):
        scanner = FileScanner()
        result = scanner.scan(multi_fov_tiff_dir)
        groups = build_file_groups(result)

        for g in groups:
            assert g.channels == ["00", "01"]
            assert len(g.files) == 2

    def test_group_has_correct_shape(self, multi_fov_tiff_dir: Path):
        scanner = FileScanner()
        result = scanner.scan(multi_fov_tiff_dir)
        groups = build_file_groups(result)

        shapes = {g.token: g.shape for g in groups}
        assert shapes["alpha"][:2] == (64, 64)
        assert shapes["beta"][:2] == (128, 128)
        assert shapes["gamma"][:2] == (32, 32)

    def test_single_fov_returns_one_group(self, single_fov_tiff_dir: Path):
        scanner = FileScanner()
        result = scanner.scan(single_fov_tiff_dir)
        groups = build_file_groups(result)

        assert len(groups) == 1
        assert groups[0].token == "sample"


# ---------------------------------------------------------------------------
# show_file_group_table tests
# ---------------------------------------------------------------------------


class TestShowFileGroupTable:
    def test_renders_without_crash(self, multi_fov_tiff_dir: Path):
        scanner = FileScanner()
        result = scanner.scan(multi_fov_tiff_dir)
        groups = build_file_groups(result)
        # Should not raise
        show_file_group_table(groups)

    def test_renders_with_assignments(self, multi_fov_tiff_dir: Path):
        scanner = FileScanner()
        result = scanner.scan(multi_fov_tiff_dir)
        groups = build_file_groups(result)
        assignments = {"alpha": ("ctrl", "N1", "FOV_001")}
        # Should not raise
        show_file_group_table(groups, assignments=assignments)


# ---------------------------------------------------------------------------
# next_fov_number tests
# ---------------------------------------------------------------------------


class TestNextFovNumber:
    def test_empty_experiment_returns_1(self, tmp_path: Path):
        with ExperimentStore.create(tmp_path / "test.percell") as store:
            store.add_condition("ctrl")
            num = next_fov_number(store, "ctrl", "N1")
            assert num == 1

    def test_increments_from_existing(self, tmp_path: Path):
        with ExperimentStore.create(tmp_path / "test.percell") as store:
            store.add_condition("ctrl")
            data = np.zeros((32, 32), dtype=np.uint16)
            store.add_fov("FOV_001", "ctrl", bio_rep="N1", width=32, height=32)
            store.add_fov("FOV_002", "ctrl", bio_rep="N1", width=32, height=32)
            num = next_fov_number(store, "ctrl", "N1")
            assert num == 3


# ---------------------------------------------------------------------------
# _parse_group_selection tests
# ---------------------------------------------------------------------------


class TestParseGroupSelection:
    def test_all_keyword(self):
        unassigned = [(0, "a"), (2, "c"), (4, "e")]
        result = _parse_group_selection("all", unassigned)
        assert result == [0, 2, 4]

    def test_space_separated_numbers(self):
        unassigned = [(0, "a"), (1, "b"), (2, "c")]
        result = _parse_group_selection("1 3", unassigned)
        assert result == [0, 2]

    def test_invalid_input_returns_empty(self):
        unassigned = [(0, "a"), (1, "b")]
        result = _parse_group_selection("abc", unassigned)
        assert result == []

    def test_out_of_range_returns_empty(self):
        unassigned = [(0, "a"), (1, "b")]
        result = _parse_group_selection("0 5", unassigned)
        assert result == []


# ---------------------------------------------------------------------------
# _prompt_condition_for_assignment tests
# ---------------------------------------------------------------------------


class TestPromptConditionForAssignment:
    def test_existing_conditions_shown(self, tmp_path: Path):
        with ExperimentStore.create(tmp_path / "test.percell") as store:
            store.add_condition("ctrl")
            store.add_condition("treated")
            # Pick existing condition "ctrl" (item 1)
            with patch.object(console, "input", return_value="1"):
                result = _prompt_condition_for_assignment(store)
            assert result == "ctrl"

    def test_new_condition_option(self, tmp_path: Path):
        with ExperimentStore.create(tmp_path / "test.percell") as store:
            store.add_condition("ctrl")
            # Pick "(new condition)" (item 2), then type name
            with patch.object(console, "input", side_effect=["2", "my_cond"]):
                result = _prompt_condition_for_assignment(store)
            assert result == "my_cond"

    def test_empty_experiment_prompts_text(self, tmp_path: Path):
        with ExperimentStore.create(tmp_path / "test.percell") as store:
            with patch.object(console, "input", return_value="my_cond"):
                result = _prompt_condition_for_assignment(store)
            assert result == "my_cond"


# ---------------------------------------------------------------------------
# _prompt_bio_rep_for_assignment tests
# ---------------------------------------------------------------------------


class TestPromptBioRepForAssignment:
    def test_existing_bio_reps_shown(self, tmp_path: Path):
        with ExperimentStore.create(tmp_path / "test.percell") as store:
            store.add_condition("ctrl")
            data = np.zeros((32, 32), dtype=np.uint16)
            store.add_fov("fov1", "ctrl", bio_rep="N1", width=32, height=32)
            store.add_fov("fov2", "ctrl", bio_rep="N2", width=32, height=32)
            # Pick "N1" (item 1)
            with patch.object(console, "input", return_value="1"):
                result = _prompt_bio_rep_for_assignment(store, "ctrl")
            assert result == "N1"

    def test_no_existing_prompts_default(self, tmp_path: Path):
        with ExperimentStore.create(tmp_path / "test.percell") as store:
            store.add_condition("ctrl")
            # Empty input → default "N1"
            with patch.object(console, "input", return_value=""):
                result = _prompt_bio_rep_for_assignment(store, "ctrl")
            assert result == "N1"
