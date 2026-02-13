"""FileScanner — directory walking and token-based filename parsing."""

from __future__ import annotations

import re
from pathlib import Path

from percell3.io.models import DiscoveredFile, ScanResult, TokenConfig
from percell3.io.tiff import read_tiff_metadata


class FileScanner:
    """Scans directories for TIFF files and parses filename tokens."""

    TIFF_EXTENSIONS = {".tif", ".tiff"}

    def scan(
        self,
        path: Path,
        token_config: TokenConfig | None = None,
    ) -> ScanResult:
        """Scan a directory for TIFF files and parse filename tokens.

        Args:
            path: Directory to scan.
            token_config: Token patterns for filename parsing.
                Uses defaults if not provided.

        Returns:
            ScanResult with discovered files and extracted dimensions.

        Raises:
            FileNotFoundError: If path does not exist.
            ValueError: If path is not a directory or contains no TIFF files.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Source path does not exist: {path}")
        if not path.is_dir():
            raise ValueError(f"Source path is not a directory: {path}")

        config = token_config or TokenConfig()
        tiff_paths = sorted(self._find_tiffs(path))

        if not tiff_paths:
            raise ValueError(f"No TIFF files found in: {path}")

        files: list[DiscoveredFile] = []
        warnings: list[str] = []
        pixel_sizes: list[float] = []

        for tiff_path in tiff_paths:
            tokens = self._parse_tokens(tiff_path, config)
            try:
                meta = read_tiff_metadata(tiff_path)
            except Exception as exc:
                warnings.append(f"Could not read metadata from {tiff_path.name}: {exc}")
                continue

            ps = meta.get("pixel_size_um")
            if ps is not None:
                pixel_sizes.append(ps)

            df = DiscoveredFile(
                path=tiff_path,
                tokens=tokens,
                shape=tuple(meta["shape"]),
                dtype=meta["dtype"],
                pixel_size_um=ps,
            )
            files.append(df)

        # Extract unique dimension values
        channels = sorted({f.tokens["channel"] for f in files if "channel" in f.tokens})
        regions = sorted({f.tokens["region"] for f in files if "region" in f.tokens})
        timepoints = sorted({f.tokens["timepoint"] for f in files if "timepoint" in f.tokens})
        z_slices = sorted({f.tokens["z_slice"] for f in files if "z_slice" in f.tokens})

        # Check pixel size consistency
        scan_pixel_size: float | None = None
        if pixel_sizes:
            unique_ps = set(round(ps, 6) for ps in pixel_sizes)
            if len(unique_ps) == 1:
                scan_pixel_size = pixel_sizes[0]
            else:
                warnings.append(
                    f"Inconsistent pixel sizes across files: {sorted(unique_ps)}"
                )
                scan_pixel_size = pixel_sizes[0]

        # Check shape consistency
        shapes = {f.shape for f in files}
        if len(shapes) > 1:
            warnings.append(f"Inconsistent shapes across files: {sorted(shapes)}")

        return ScanResult(
            source_path=path,
            files=files,
            channels=channels,
            regions=regions,
            timepoints=timepoints,
            z_slices=z_slices,
            pixel_size_um=scan_pixel_size,
            warnings=warnings,
        )

    def _find_tiffs(self, path: Path) -> list[Path]:
        """Walk directory tree for TIFF files."""
        results = []
        for child in path.rglob("*"):
            if child.is_file() and child.suffix.lower() in self.TIFF_EXTENSIONS:
                results.append(child)
        return results

    def _parse_tokens(self, path: Path, config: TokenConfig) -> dict[str, str]:
        """Parse filename tokens using the configured regex patterns."""
        stem = path.stem
        tokens: dict[str, str] = {}

        # Channel
        m = re.search(config.channel, stem)
        if m:
            tokens["channel"] = m.group(1)

        # Timepoint
        m = re.search(config.timepoint, stem)
        if m:
            tokens["timepoint"] = m.group(1)

        # Z-slice
        m = re.search(config.z_slice, stem)
        if m:
            tokens["z_slice"] = m.group(1)

        # Region — use custom pattern or derive from remaining text
        if config.region is not None:
            m = re.search(config.region, stem)
            if m:
                tokens["region"] = m.group(1)
        else:
            # Derive region by stripping all matched tokens
            region = stem
            for pattern in (config.channel, config.timepoint, config.z_slice):
                region = re.sub(pattern, "", region)
            region = region.strip("_- ")
            if region:
                tokens["region"] = region

        return tokens
