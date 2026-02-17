"""BatchMeasurer — measure all FOVs x all channels efficiently."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

from percell3.measure.measurer import Measurer
from percell3.measure.metrics import MetricRegistry

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


class BatchMeasurer:
    """Efficiently measure all FOVs x all channels in an experiment.

    Args:
        metrics: Optional MetricRegistry. If None, uses default builtins.
    """

    def __init__(self, metrics: MetricRegistry | None = None) -> None:
        self._metrics = metrics or MetricRegistry()

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
                    fov=fov_info.name,
                    condition=fov_info.condition,
                    channels=channels,
                    metrics=metrics,
                    bio_rep=fov_info.bio_rep,
                )
                total_measurements += count
                fovs_processed += 1

                if count == 0:
                    warnings.append(
                        f"{fov_info.name}: 0 measurements (no cells?)"
                    )

            except Exception as exc:
                if isinstance(exc, (MemoryError, KeyboardInterrupt, SystemExit)):
                    raise
                logger.warning(
                    "Measurement failed for FOV %s: %s",
                    fov_info.name, exc, exc_info=True,
                )
                warnings.append(
                    f"{fov_info.name}: measurement failed — {exc}"
                )

            if progress_callback:
                progress_callback(i + 1, total, fov_info.name)

        elapsed = time.monotonic() - start

        return BatchResult(
            total_measurements=total_measurements,
            fovs_processed=fovs_processed,
            channels_measured=len(channels),
            elapsed_seconds=round(elapsed, 3),
            warnings=warnings,
        )
