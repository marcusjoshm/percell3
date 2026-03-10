"""Tests for percell4.cli.main — Click commands with Rich output.

Uses click.testing.CliRunner for deterministic CLI testing.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pytest
import tifffile
from click.testing import CliRunner

from percell4.cli.main import cli

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
SAMPLE_TOML = FIXTURES_DIR / "sample_experiment.toml"


@pytest.fixture()
def runner() -> CliRunner:
    """Create a Click CliRunner."""
    return CliRunner()


@pytest.fixture()
def sample_toml(tmp_path: Path) -> Path:
    """Copy sample TOML to tmp_path so Click exists=True works."""
    dest = tmp_path / "experiment.toml"
    dest.write_text(SAMPLE_TOML.read_text())
    return dest


@pytest.fixture()
def created_experiment(tmp_path: Path, sample_toml: Path) -> Path:
    """Create a .percell experiment in tmp_path and return its path."""
    percell_path = tmp_path / "test.percell"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["create", str(sample_toml), "--path", str(percell_path)],
    )
    assert result.exit_code == 0, result.output
    return percell_path


def _write_test_tiff(path: Path, shape: tuple = (64, 64), dtype=np.uint16) -> np.ndarray:
    """Write a synthetic TIFF file for import tests."""
    arr = np.random.randint(0, 1000, shape, dtype=dtype)
    tifffile.imwrite(str(path), arr)
    return arr


# ---------------------------------------------------------------------------
# Tests: Help and basic commands
# ---------------------------------------------------------------------------


class TestHelpAndBasics:
    """Tests for --help output and basic CLI behavior."""

    def test_help_shows_commands(self, runner: CliRunner) -> None:
        """Running --help lists available subcommands."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        # Verify key commands appear in help
        assert "create" in result.output
        assert "status" in result.output
        assert "import" in result.output
        assert "export" in result.output
        assert "segment" in result.output
        assert "measure" in result.output
        assert "merge" in result.output
        assert "plugins" in result.output

    def test_unknown_command_error(self, runner: CliRunner) -> None:
        """An unknown subcommand produces an error."""
        result = runner.invoke(cli, ["nonexistent-command"])
        assert result.exit_code != 0

    def test_no_experiment_error(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Commands requiring --experiment fail gracefully without it."""
        # Point to a non-existent recent.json so auto-load cannot find one
        monkeypatch.setattr(
            "percell4.cli.main._try_auto_load", lambda: None
        )
        result = runner.invoke(cli, ["status"])
        assert result.exit_code != 0
        assert "Error" in result.output or "experiment" in result.output.lower()


# ---------------------------------------------------------------------------
# Tests: create
# ---------------------------------------------------------------------------


class TestCreateCommand:
    """Tests for the 'create' command."""

    def test_create_command(self, runner: CliRunner, sample_toml: Path, tmp_path: Path) -> None:
        """Create command produces a .percell directory."""
        out = tmp_path / "new.percell"
        result = runner.invoke(
            cli,
            ["create", str(sample_toml), "--path", str(out)],
        )
        assert result.exit_code == 0, result.output
        assert "OK:" in result.output or "Created" in result.output
        assert (out / "experiment.db").exists()

    def test_create_auto_name(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Create without --path uses config stem as name."""
        toml_path = tmp_path / "my_project.toml"
        toml_path.write_text(SAMPLE_TOML.read_text())
        # Run from tmp_path so auto-generated path goes there
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(
            cli,
            ["create", str(toml_path)],
        )
        assert result.exit_code == 0, result.output
        assert (tmp_path / "my_project.percell" / "experiment.db").exists()

    def test_create_already_exists_error(
        self, runner: CliRunner, sample_toml: Path, tmp_path: Path
    ) -> None:
        """Creating into a non-empty directory produces an error."""
        out = tmp_path / "existing.percell"
        out.mkdir()
        (out / "dummy.txt").write_text("occupied")
        result = runner.invoke(
            cli,
            ["create", str(sample_toml), "--path", str(out)],
        )
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Tests: create then status
# ---------------------------------------------------------------------------


class TestCreateThenStatus:
    """Tests for create -> status workflow."""

    def test_create_then_status(
        self, runner: CliRunner, created_experiment: Path
    ) -> None:
        """Status command works on a freshly created experiment."""
        result = runner.invoke(
            cli,
            ["-e", str(created_experiment), "status"],
        )
        assert result.exit_code == 0, result.output
        assert "Test Experiment" in result.output
        # No FOVs yet
        assert "No FOVs" in result.output


# ---------------------------------------------------------------------------
# Tests: init
# ---------------------------------------------------------------------------


class TestInitCommand:
    """Tests for the 'init' command."""

    def test_init_creates_toml(self, runner: CliRunner, tmp_path: Path) -> None:
        """Init creates a TOML file with required sections."""
        out = tmp_path / "generated.toml"
        result = runner.invoke(cli, ["init", "--path", str(out)])
        assert result.exit_code == 0, result.output
        assert out.exists()
        content = out.read_text()
        assert "[experiment]" in content
        assert "[[channels]]" in content
        assert "[[roi_types]]" in content

    def test_init_template_has_comments(self, runner: CliRunner, tmp_path: Path) -> None:
        """Init with --template includes commented examples."""
        out = tmp_path / "template.toml"
        result = runner.invoke(cli, ["init", "--path", str(out), "--template"])
        assert result.exit_code == 0, result.output
        content = out.read_text()
        assert "#" in content
        assert "particle" in content
        assert "cellpose" in content

    def test_init_existing_file_error(self, runner: CliRunner, tmp_path: Path) -> None:
        """Init refuses to overwrite an existing file."""
        out = tmp_path / "exists.toml"
        out.write_text("existing content")
        result = runner.invoke(cli, ["init", "--path", str(out)])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Tests: import
# ---------------------------------------------------------------------------


class TestImportCommand:
    """Tests for the 'import' command."""

    def test_import_command(
        self, runner: CliRunner, created_experiment: Path, tmp_path: Path
    ) -> None:
        """Import command ingests TIFF files into the experiment."""
        # Create test TIFFs in a source directory
        src = tmp_path / "images"
        src.mkdir()
        _write_test_tiff(src / "fov_001.tif", (64, 64))
        _write_test_tiff(src / "fov_002.tif", (64, 64))

        result = runner.invoke(
            cli,
            ["-e", str(created_experiment), "import", str(src)],
        )
        assert result.exit_code == 0, result.output
        assert "Imported 2 FOVs" in result.output

    def test_import_empty_dir_warning(
        self, runner: CliRunner, created_experiment: Path, tmp_path: Path
    ) -> None:
        """Import from an empty directory shows a warning."""
        empty = tmp_path / "empty"
        empty.mkdir()
        result = runner.invoke(
            cli,
            ["-e", str(created_experiment), "import", str(empty)],
        )
        assert result.exit_code == 0
        assert "No image files" in result.output or "Warning" in result.output


# ---------------------------------------------------------------------------
# Tests: export
# ---------------------------------------------------------------------------


class TestExportCommand:
    """Tests for the 'export' command."""

    def test_export_command(
        self, runner: CliRunner, created_experiment: Path, tmp_path: Path
    ) -> None:
        """Export produces a CSV file (may be empty if no measurements)."""
        out_csv = tmp_path / "output.csv"

        # First import some data
        src = tmp_path / "images"
        src.mkdir()
        _write_test_tiff(src / "fov_001.tif", (32, 32))
        runner.invoke(
            cli,
            ["-e", str(created_experiment), "import", str(src)],
        )

        # Export (no measurements yet, but command should succeed)
        result = runner.invoke(
            cli,
            ["-e", str(created_experiment), "export", str(out_csv)],
        )
        assert result.exit_code == 0, result.output

    def test_export_overwrite_guard(
        self, runner: CliRunner, created_experiment: Path, tmp_path: Path
    ) -> None:
        """Export refuses to overwrite without --overwrite flag."""
        out_csv = tmp_path / "existing.csv"
        out_csv.write_text("old data")
        result = runner.invoke(
            cli,
            ["-e", str(created_experiment), "export", str(out_csv)],
        )
        assert result.exit_code != 0
        assert "exists" in result.output.lower() or "overwrite" in result.output.lower()


# ---------------------------------------------------------------------------
# Tests: merge
# ---------------------------------------------------------------------------


class TestMergeCommand:
    """Tests for the 'merge' command."""

    def test_merge_command(
        self, runner: CliRunner, sample_toml: Path, tmp_path: Path
    ) -> None:
        """Merge two experiments into one."""
        exp_a = tmp_path / "a.percell"
        exp_b = tmp_path / "b.percell"

        # Create two experiments
        result_a = runner.invoke(
            cli,
            ["create", str(sample_toml), "--path", str(exp_a)],
        )
        assert result_a.exit_code == 0, result_a.output

        result_b = runner.invoke(
            cli,
            ["create", str(sample_toml), "--path", str(exp_b)],
        )
        assert result_b.exit_code == 0, result_b.output

        # Merge b into a
        result = runner.invoke(
            cli,
            ["-e", str(exp_a), "merge", str(exp_b)],
        )
        assert result.exit_code == 0, result.output
        assert "Merged" in result.output or "complete" in result.output.lower()


# ---------------------------------------------------------------------------
# Tests: plugins listing
# ---------------------------------------------------------------------------


class TestPluginsCommand:
    """Tests for the 'plugins' command."""

    def test_plugins_list(self, runner: CliRunner) -> None:
        """Plugins command without --run lists available plugins."""
        result = runner.invoke(cli, ["plugins"])
        assert result.exit_code == 0, result.output
        # Should show at least some plugins or empty message


# ---------------------------------------------------------------------------
# Tests: status with data
# ---------------------------------------------------------------------------


class TestStatusWithData:
    """Tests for status command after importing data."""

    def test_status_shows_fov_counts(
        self, runner: CliRunner, created_experiment: Path, tmp_path: Path
    ) -> None:
        """Status shows FOV counts after import."""
        src = tmp_path / "imgs"
        src.mkdir()
        _write_test_tiff(src / "a.tif", (16, 16))

        runner.invoke(
            cli,
            ["-e", str(created_experiment), "import", str(src)],
        )

        result = runner.invoke(
            cli,
            ["-e", str(created_experiment), "status"],
        )
        assert result.exit_code == 0, result.output
        assert "imported" in result.output.lower()
        assert "1" in result.output


# ---------------------------------------------------------------------------
# Tests: export-prism
# ---------------------------------------------------------------------------


class TestExportPrism:
    """Tests for the 'export-prism' command."""

    def test_export_prism_creates_directory(
        self, runner: CliRunner, created_experiment: Path, tmp_path: Path
    ) -> None:
        """Export-prism creates output directory."""
        out_dir = tmp_path / "prism_out"
        result = runner.invoke(
            cli,
            ["-e", str(created_experiment), "export-prism", str(out_dir)],
        )
        assert result.exit_code == 0, result.output
        assert out_dir.exists()


# ---------------------------------------------------------------------------
# Tests: init edge cases
# ---------------------------------------------------------------------------


class TestInitEdgeCases:
    """Additional tests for init command."""

    def test_init_default_path(self, runner: CliRunner, tmp_path: Path) -> None:
        """Init with default path creates experiment.toml in cwd."""
        import os
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = runner.invoke(cli, ["init"])
            assert result.exit_code == 0, result.output
            assert (tmp_path / "experiment.toml").exists()
        finally:
            os.chdir(original_cwd)
