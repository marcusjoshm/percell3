"""BatchMeasurer — measure all FOVs x all channels efficiently."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

from percell3.measure.measurer import Measurer
from percell3.measure.metrics import MetricRegistry
from percell3.measure.particle_analyzer import ParticleAnalyzer

if TYPE_CHECKING:
    from percell3.core import ExperimentStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BatchResult:
    """Result of a batch measurement run.

    Attributes:
        total_measurements: Total number of measurement records written.
        fovs_processed: Number of FOVs processed.
        channels_measured: Number of channels measured per FOV.
        elapsed_seconds: Wall-clock time in seconds.
        warnings: List of warning messages.
    """

    total_measurements: int
    fovs_processed: int
    channels_measured: int
    elapsed_seconds: float
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ConfigBatchResult:
    """Result of a config-driven batch measurement.

    Attributes:
        entries_processed: Number of config entries successfully processed.
        entries_skipped: Number of entries skipped (already measured).
        total_measurements: Total measurement records written.
        total_particles: Total particles extracted.
        elapsed_seconds: Wall-clock time in seconds.
        warnings: List of warning messages.
    """

    entries_processed: int
    entries_skipped: int
    total_measurements: int
    total_particles: int
    elapsed_seconds: float
    warnings: list[str] = field(default_factory=list)


class BatchMeasurer:
    """Efficiently measure all FOVs x all channels in an experiment.

    Args:
        metrics: Optional MetricRegistry. If None, uses default builtins.
    """

    def __init__(
        self,
        metrics: MetricRegistry | None = None,
        min_particle_area: int = 5,
    ) -> None:
        self._metrics = metrics or MetricRegistry()
        self._min_particle_area = min_particle_area

    def measure_config(
        self,
        store: ExperimentStore,
        config_id: int,
        force: bool = False,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> ConfigBatchResult:
        """Execute measurements for all entries in a measurement configuration.

        For each config entry:
        1. Measure whole_cell metrics for the segmentation run
        2. If threshold_run_id is set: measure mask-scoped metrics + extract particles

        Args:
            store: Target ExperimentStore.
            config_id: Measurement config ID.
            force: If True, re-measure even if measurements exist.
            progress_callback: Optional callback(current, total, fov_name).

        Returns:
            ConfigBatchResult with measurement statistics.
        """
        start = time.monotonic()
        warnings: list[str] = []

        entries = store.get_measurement_config_entries(config_id)
        if not entries:
            return ConfigBatchResult(
                entries_processed=0, entries_skipped=0,
                total_measurements=0, total_particles=0,
                elapsed_seconds=0.0,
            )

        # Resolve all channels once
        all_channels = store.get_channels()
        channel_names = [ch.name for ch in all_channels]

        measurer = Measurer(metrics=self._metrics)
        analyzer = ParticleAnalyzer(min_particle_area=self._min_particle_area)

        entries_processed = 0
        entries_skipped = 0
        total_measurements = 0
        total_particles = 0
        affected_fov_ids: set[int] = set()
        total = len(entries)

        for i, entry in enumerate(entries):
            fov_id = entry.fov_id
            seg_run_id = entry.segmentation_run_id
            thresh_run_id = entry.threshold_run_id

            fov_info = store.get_fov_by_id(fov_id)
            fov_name = fov_info.display_name

            # Skip-if-measured check
            if not force and self._has_measurements(
                store, fov_id, seg_run_id, thresh_run_id,
            ):
                entries_skipped += 1
                if progress_callback:
                    progress_callback(i + 1, total, fov_name)
                continue

            try:
                # 1. Whole-cell measurements
                count = measurer.measure_fov(
                    store, fov_id=fov_id, channels=channel_names,
                    segmentation_run_id=seg_run_id,
                )
                total_measurements += count

                # 2. Mask-scoped measurements + particle extraction
                if thresh_run_id is not None:
                    thresh_run = store.get_threshold_run(thresh_run_id)
                    channel = thresh_run.channel

                    mask_count = measurer.measure_fov_masked(
                        store, fov_id=fov_id, channels=channel_names,
                        threshold_channel=channel,
                        threshold_run_id=thresh_run_id,
                        scopes=["mask_inside", "mask_outside"],
                        segmentation_run_id=seg_run_id,
                    )
                    total_measurements += mask_count

                    # Extract particles
                    cells_df = store.get_cells(fov_id=fov_id)
                    seg_cells = cells_df[
                        cells_df["segmentation_id"] == seg_run_id
                    ]
                    cell_ids = seg_cells["id"].tolist()
                    if cell_ids:
                        # Delete existing particles for re-measure
                        if force:
                            store.delete_particles_for_threshold_run(
                                thresh_run_id,
                            )

                        pa_result = analyzer.analyze_fov(
                            store, fov_id=fov_id, channel=channel,
                            threshold_run_id=thresh_run_id,
                            cell_ids=cell_ids,
                            segmentation_run_id=seg_run_id,
                        )
                        if pa_result.particles:
                            store.add_particles(pa_result.particles)
                        if pa_result.summary_measurements:
                            store.add_measurements(pa_result.summary_measurements)
                            total_measurements += len(pa_result.summary_measurements)
                        store.write_particle_labels(
                            fov_id, channel,
                            pa_result.particle_label_image,
                            thresh_run_id,
                        )
                        total_particles += pa_result.total_particles

                entries_processed += 1
                affected_fov_ids.add(fov_id)

            except Exception as exc:
                if isinstance(exc, (MemoryError, KeyboardInterrupt, SystemExit)):
                    raise
                logger.warning(
                    "Config entry failed for FOV %s: %s",
                    fov_name, exc, exc_info=True,
                )
                warnings.append(f"{fov_name}: measurement failed — {exc}")

            if progress_callback:
                progress_callback(i + 1, total, fov_name)

        # Batch status cache rebuild
        if affected_fov_ids:
            store.update_fov_status_cache_batch(list(affected_fov_ids))

        elapsed = time.monotonic() - start

        return ConfigBatchResult(
            entries_processed=entries_processed,
            entries_skipped=entries_skipped,
            total_measurements=total_measurements,
            total_particles=total_particles,
            elapsed_seconds=round(elapsed, 3),
            warnings=warnings,
        )

    @staticmethod
    def _has_measurements(
        store: ExperimentStore,
        fov_id: int,
        segmentation_run_id: int,
        threshold_run_id: int | None,
    ) -> bool:
        """Check if measurements already exist for a config entry."""
        cells_df = store.get_cells(fov_id=fov_id)
        if cells_df.empty:
            return False

        # Filter to cells from this segmentation run
        if "segmentation_id" not in cells_df.columns:
            return False
        seg_cells = cells_df[cells_df["segmentation_id"] == segmentation_run_id]
        if seg_cells.empty:
            return False

        cell_ids = seg_cells["id"].tolist()
        measurements = store.get_measurements(
            cell_ids=cell_ids, scope="whole_cell",
        )
        if measurements.empty:
            return False

        # If threshold run specified, also check mask-scoped measurements
        if threshold_run_id is not None:
            masked = store.get_measurements(
                cell_ids=cell_ids, scope="mask_inside",
            )
            if masked.empty or "threshold_run_id" not in masked.columns:
                return False
            if not (masked["threshold_run_id"] == threshold_run_id).any():
                return False

        return True

    def measure_experiment(
        self,
        store: ExperimentStore,
        channels: list[str] | None = None,
        metrics: list[str] | None = None,
        condition: str | None = None,
        bio_rep: str | None = None,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> BatchResult:
        """Measure all cells in all FOVs across specified channels.

        Args:
            store: Target ExperimentStore.
            channels: Channel names to measure. None = all channels.
            metrics: Metric names. None = all registered metrics.
            condition: Optional condition filter.
            bio_rep: Optional biological replicate filter.
            progress_callback: Optional callback(current, total, fov_name).

        Returns:
            BatchResult with measurement statistics.

        Raises:
            ValueError: If no channels or no FOVs exist.
        """
        start = time.monotonic()
        warnings: list[str] = []

        # Resolve channels
        if channels is None:
            all_channels = store.get_channels()
            channels = [ch.name for ch in all_channels]

        if not channels:
            raise ValueError("No channels to measure")

        # Get FOVs
        all_fovs = store.get_fovs(condition=condition, bio_rep=bio_rep)
        if not all_fovs:
            raise ValueError(
                f"No fovs found"
                + (f" for condition={condition!r}" if condition else "")
            )

        measurer = Measurer(metrics=self._metrics)
        total_measurements = 0
        fovs_processed = 0
        total = len(all_fovs)

        for i, fov_info in enumerate(all_fovs):
            try:
                count = measurer.measure_fov(
                    store,
                    fov_id=fov_info.id,
                    channels=channels,
                    metrics=metrics,
                )
                total_measurements += count
                fovs_processed += 1

                if count == 0:
                    warnings.append(
                        f"{fov_info.display_name}: 0 measurements (no cells?)"
                    )

            except Exception as exc:
                if isinstance(exc, (MemoryError, KeyboardInterrupt, SystemExit)):
                    raise
                logger.warning(
                    "Measurement failed for FOV %s: %s",
                    fov_info.display_name, exc, exc_info=True,
                )
                warnings.append(
                    f"{fov_info.display_name}: measurement failed — {exc}"
                )

            if progress_callback:
                progress_callback(i + 1, total, fov_info.display_name)

        elapsed = time.monotonic() - start

        return BatchResult(
            total_measurements=total_measurements,
            fovs_processed=fovs_processed,
            channels_measured=len(channels),
            elapsed_seconds=round(elapsed, 3),
            warnings=warnings,
        )
