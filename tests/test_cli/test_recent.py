"""Tests for the recent experiments history module."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from percell3.cli import _recent


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect _recent to use a temp directory instead of ~/.config."""
    config_dir = tmp_path / "config"
    recent_file = config_dir / "recent.json"
    monkeypatch.setattr(_recent, "_CONFIG_DIR", config_dir)
    monkeypatch.setattr(_recent, "_RECENT_FILE", recent_file)


class TestLoadRecent:
    def test_empty_when_no_file(self):
        assert _recent.load_recent() == []

    def test_loads_valid_json(self, tmp_path: Path):
        # Create a real experiment directory so paths are "valid"
        exp = tmp_path / "exp1.percell"
        exp.mkdir()
        _recent._RECENT_FILE.parent.mkdir(parents=True, exist_ok=True)
        _recent._RECENT_FILE.write_text(json.dumps([str(exp)]))
        result = _recent.load_recent()
        assert result == [str(exp)]

    def test_prunes_nonexistent_paths(self, tmp_path: Path):
        exp = tmp_path / "exp1.percell"
        exp.mkdir()
        _recent._RECENT_FILE.parent.mkdir(parents=True, exist_ok=True)
        _recent._RECENT_FILE.write_text(
            json.dumps([str(exp), "/nonexistent/path.percell"])
        )
        result = _recent.load_recent()
        assert result == [str(exp)]

    def test_corrupted_json_returns_empty(self):
        _recent._RECENT_FILE.parent.mkdir(parents=True, exist_ok=True)
        _recent._RECENT_FILE.write_text("NOT JSON{{{")
        assert _recent.load_recent() == []

    def test_non_list_json_returns_empty(self):
        _recent._RECENT_FILE.parent.mkdir(parents=True, exist_ok=True)
        _recent._RECENT_FILE.write_text(json.dumps({"key": "value"}))
        assert _recent.load_recent() == []

    def test_permission_error_returns_empty(self):
        with patch.object(Path, "exists", side_effect=OSError("denied")):
            assert _recent.load_recent() == []


class TestAddToRecent:
    def test_adds_path(self, tmp_path: Path):
        exp = tmp_path / "exp.percell"
        exp.mkdir()
        _recent.add_to_recent(exp)
        assert _recent.load_recent() == [str(exp.resolve())]

    def test_moves_existing_to_front(self, tmp_path: Path):
        exp1 = tmp_path / "exp1.percell"
        exp2 = tmp_path / "exp2.percell"
        exp1.mkdir()
        exp2.mkdir()
        _recent.add_to_recent(exp1)
        _recent.add_to_recent(exp2)
        _recent.add_to_recent(exp1)
        result = _recent.load_recent()
        assert result == [str(exp1.resolve()), str(exp2.resolve())]

    def test_max_10_entries(self, tmp_path: Path):
        paths = []
        for i in range(12):
            p = tmp_path / f"exp{i}.percell"
            p.mkdir()
            paths.append(p)
            _recent.add_to_recent(p)
        result = _recent.load_recent()
        assert len(result) == 10
        # Most recent should be first
        assert result[0] == str(paths[-1].resolve())

    def test_no_duplicates(self, tmp_path: Path):
        exp = tmp_path / "exp.percell"
        exp.mkdir()
        _recent.add_to_recent(exp)
        _recent.add_to_recent(exp)
        _recent.add_to_recent(exp)
        assert len(_recent.load_recent()) == 1
