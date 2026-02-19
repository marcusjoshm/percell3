"""Tests for percell3 segmentation menu helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from percell3.cli.menu import (
    _build_model_list,
    _select_fovs_from_table,
    _show_fov_status_table,
)
from percell3.cli.utils import console
from percell3.core import ExperimentStore
from percell3.core.models import CellRecord


# ---------------------------------------------------------------------------
# _build_model_list tests
# ---------------------------------------------------------------------------


class TestBuildModelList:
    def test_cpsam_is_first(self):
        models = _build_model_list()
        assert models[0] == "cpsam"

    def test_all_known_models_included(self):
        from percell3.segment.cellpose_adapter import KNOWN_CELLPOSE_MODELS

        models = _build_model_list()
        assert set(models) == KNOWN_CELLPOSE_MODELS

    def test_rest_is_sorted(self):
        models = _build_model_list()
        rest = models[1:]
        assert rest == sorted(rest)


# ---------------------------------------------------------------------------
# _show_fov_status_table tests
# ---------------------------------------------------------------------------


class TestShowFovStatusTable:
    def test_renders_without_crash(self, tmp_path: Path):
        with ExperimentStore.create(tmp_path / "test.percell") as store:
            store.add_condition("ctrl")
            fov_id = store.add_fov("FOV_001", "ctrl", width=64, height=64)
            fovs = store.get_fovs()
            summary = {fov_id: (0, None)}
            # Should not raise
            _show_fov_status_table(fovs, summary)

    def test_renders_with_segmentation_data(self, tmp_path: Path):
        with ExperimentStore.create(tmp_path / "test.percell") as store:
            store.add_condition("ctrl")
            fov_id = store.add_fov("FOV_001", "ctrl", width=64, height=64)
            fovs = store.get_fovs()
            summary = {fov_id: (100, "cpsam")}
            # Should not raise
            _show_fov_status_table(fovs, summary)


# ---------------------------------------------------------------------------
# _select_fovs_from_table tests
# ---------------------------------------------------------------------------


class TestSelectFovsFromTable:
    @pytest.fixture
    def fovs(self, tmp_path: Path):
        with ExperimentStore.create(tmp_path / "test.percell") as store:
            store.add_condition("ctrl")
            store.add_condition("treated")
            store.add_fov("FOV_001", "ctrl", width=64, height=64)
            store.add_fov("FOV_001", "treated", width=64, height=64)
            store.add_fov("FOV_002", "ctrl", width=64, height=64)
            yield store.get_fovs()

    def test_all_keyword(self, fovs):
        with patch.object(console, "input", return_value="all"):
            result = _select_fovs_from_table(fovs)
        assert len(result) == 3

    def test_blank_defaults_to_all(self, fovs):
        with patch.object(console, "input", return_value=""):
            result = _select_fovs_from_table(fovs)
        assert len(result) == 3

    def test_space_separated_numbers(self, fovs):
        with patch.object(console, "input", return_value="1 3"):
            result = _select_fovs_from_table(fovs)
        assert len(result) == 2
        assert result[0].name == fovs[0].name
        assert result[1].name == fovs[2].name
