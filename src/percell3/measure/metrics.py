"""Built-in measurement metrics and metric registry."""

from __future__ import annotations

from typing import Callable

import numpy as np

# Metric function signature: (channel_image_crop, cell_binary_mask) -> float
MetricFunction = Callable[[np.ndarray, np.ndarray], float]


def mean_intensity(image: np.ndarray, mask: np.ndarray) -> float:
    """Average pixel intensity within the cell mask."""
    return float(np.mean(image[mask]))


def max_intensity(image: np.ndarray, mask: np.ndarray) -> float:
    """Maximum pixel intensity within the cell mask."""
    return float(np.max(image[mask]))


def min_intensity(image: np.ndarray, mask: np.ndarray) -> float:
    """Minimum pixel intensity within the cell mask."""
    return float(np.min(image[mask]))


def integrated_intensity(image: np.ndarray, mask: np.ndarray) -> float:
    """Total (summed) pixel intensity within the cell mask."""
    return float(np.sum(image[mask]))


def std_intensity(image: np.ndarray, mask: np.ndarray) -> float:
    """Standard deviation of pixel intensity within the cell mask."""
    return float(np.std(image[mask]))


def median_intensity(image: np.ndarray, mask: np.ndarray) -> float:
    """Median pixel intensity within the cell mask."""
    return float(np.median(image[mask]))


def area(image: np.ndarray, mask: np.ndarray) -> float:
    """Cell area in pixels (count of True pixels in mask)."""
    return float(np.sum(mask))


_BUILTIN_METRICS: dict[str, MetricFunction] = {
    "mean_intensity": mean_intensity,
    "max_intensity": max_intensity,
    "min_intensity": min_intensity,
    "integrated_intensity": integrated_intensity,
    "std_intensity": std_intensity,
    "median_intensity": median_intensity,
    "area": area,
}


class MetricRegistry:
    """Registry of available measurement metrics.

    Comes pre-loaded with 7 built-in metrics. Custom metrics can be
    registered via ``register()``.
    """

    def __init__(self) -> None:
        self._metrics: dict[str, MetricFunction] = dict(_BUILTIN_METRICS)

    def register(self, name: str, func: MetricFunction) -> None:
        """Register a custom metric function.

        Args:
            name: Metric name (e.g., "my_metric").
            func: Callable with signature (image_crop, cell_mask) -> float.

        Raises:
            ValueError: If name is empty.
        """
        if not name:
            raise ValueError("Metric name must not be empty")
        self._metrics[name] = func

    def compute(self, name: str, image: np.ndarray, mask: np.ndarray) -> float:
        """Compute a named metric for a single cell.

        Args:
            name: Registered metric name.
            image: Channel image crop (2D array).
            mask: Cell binary mask crop (2D bool array, same shape as image).

        Returns:
            Scalar metric value.

        Raises:
            KeyError: If metric name is not registered.
        """
        if name not in self._metrics:
            raise KeyError(
                f"Unknown metric {name!r}. "
                f"Available: {sorted(self._metrics)}"
            )
        return self._metrics[name](image, mask)

    def list_metrics(self) -> list[str]:
        """Return sorted list of all registered metric names."""
        return sorted(self._metrics)

    def __contains__(self, name: str) -> bool:
        return name in self._metrics

    def __len__(self) -> int:
        return len(self._metrics)
