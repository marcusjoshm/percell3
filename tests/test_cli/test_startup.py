"""Tests for CLI startup performance — heavy imports must be deferred."""

from __future__ import annotations

import subprocess
import sys


class TestLazyImports:
    def test_cli_module_does_not_eagerly_load_numpy(self):
        """Importing percell3.cli.main should NOT pull in numpy/dask/zarr.

        Uses subprocess to get a clean Python process without conftest pollution.
        """
        result = subprocess.run(
            [
                sys.executable, "-c",
                "import percell3.cli.main; "
                "import sys; "
                "heavy = [m for m in sys.modules "
                "    if m.startswith(('numpy', 'dask', 'zarr'))]; "
                "print(','.join(heavy) if heavy else 'CLEAN')"
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"Import failed: {result.stderr}"
        assert result.stdout.strip() == "CLEAN", (
            f"Heavy packages loaded during CLI startup: {result.stdout.strip()}"
        )

    def test_cli_help_completes_quickly(self):
        """percell3 --help should complete in <5s (generous bound for CI)."""
        result = subprocess.run(
            [
                sys.executable, "-c",
                "from percell3.cli.main import cli; cli(['--help'])"
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        # Click exits with code 0 on --help
        assert result.returncode == 0, f"--help failed: {result.stderr}"
        assert "PerCell 3" in result.stdout
