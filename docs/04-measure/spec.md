# Module 4: Measure — Specification

## Overview

The measurement engine computes per-cell metrics by combining label images
(from segmentation) with raw channel images. It also provides thresholding
to produce binary masks. This is the core analytical capability of PerCell 3 —
the ability to measure ANY channel using existing segmentation boundaries.

## Measurement Engine

```python
class Measurer:
    """Compute per-cell measurements."""

    def __init__(self, store: ExperimentStore):
        self.store = store
        self._metrics = MetricRegistry()

    def measure_region(self, region: str, condition: str,
                       channels: list[str],
                       metrics: list[str] = None,
                       segmentation_run_id: int = None,
                       timepoint: str = None) -> int:
        """Measure all cells in a region across specified channels.

        Args:
            region: Region name.
            condition: Condition name.
            channels: Channel names to measure.
            metrics: Metric names (default: all registered metrics).
            segmentation_run_id: Which segmentation to use (default: latest).
            timepoint: Timepoint (optional).

        Returns:
            Number of measurements written.
        """

    def measure_cells(self, cell_ids: list[int],
                      channel: str,
                      metrics: list[str] = None) -> list[MeasurementRecord]:
        """Measure specific cells on a specific channel.
        Returns measurements without writing to database (for preview)."""
```

## Built-in Metrics

```python
class MetricRegistry:
    """Registry of available measurement metrics."""

    def __init__(self):
        self._metrics: dict[str, MetricFunction] = {}
        self._register_builtins()

    def register(self, name: str, func: MetricFunction) -> None:
        """Register a custom metric function."""

    def compute(self, name: str, image: np.ndarray,
                mask: np.ndarray) -> float:
        """Compute a metric for a single cell."""
```

### Standard Metrics

| Metric Name | Formula | Description |
|-------------|---------|-------------|
| `mean_intensity` | mean(image[mask]) | Average pixel intensity in cell |
| `max_intensity` | max(image[mask]) | Maximum pixel intensity |
| `min_intensity` | min(image[mask]) | Minimum pixel intensity |
| `integrated_intensity` | sum(image[mask]) | Total pixel intensity (sum) |
| `std_intensity` | std(image[mask]) | Standard deviation of intensity |
| `median_intensity` | median(image[mask]) | Median pixel intensity |
| `area` | sum(mask) | Area in pixels (redundant with cells table, but per-channel) |
| `positive_fraction` | sum(mask & threshold_mask) / sum(mask) | Fraction of cell above threshold |

### Metric Function Signature

```python
# Type alias for metric functions
MetricFunction = Callable[[np.ndarray, np.ndarray], float]
# Args: (channel_image_region, cell_binary_mask) -> scalar value
```

## Measurement Pipeline

For each region:

```
1. Read label image from labels.zarr
2. Read raw channel image from images.zarr
3. For each cell (label value):
   a. Extract cell mask from label image (mask = labels == cell_label)
   b. Extract cell bounding box from cells table
   c. Crop both image and mask to bounding box (efficiency)
   d. Compute each requested metric
   e. Create MeasurementRecord
4. Bulk insert all MeasurementRecords
```

### Efficiency Notes
- Use bounding box from cells table to avoid processing the full image per cell
- For batch mode, read each channel image once and iterate over all cells
- Use dask for lazy loading, but compute to numpy for the actual measurement (regionprops needs numpy)
- Consider using `scipy.ndimage.labeled_comprehension` for vectorized metrics

## Thresholding Engine

```python
class ThresholdEngine:
    """Apply thresholding to produce binary masks."""

    def threshold_region(self, store: ExperimentStore,
                         region: str, condition: str, channel: str,
                         method: str = "otsu",
                         manual_value: float = None,
                         timepoint: str = None) -> ThresholdResult:
        """Apply thresholding to a channel image.

        1. Read channel image from images.zarr
        2. Compute threshold value
        3. Create binary mask
        4. Write mask to masks.zarr
        5. Log threshold run in SQLite
        6. Return result with threshold value
        """

@dataclass
class ThresholdResult:
    threshold_run_id: int
    threshold_value: float
    positive_pixels: int
    total_pixels: int
    positive_fraction: float
```

### Thresholding Methods

| Method | Implementation | Use Case |
|--------|---------------|----------|
| `otsu` | `skimage.filters.threshold_otsu()` | Default, good for bimodal distributions |
| `adaptive` | `skimage.filters.threshold_local()` | Uneven illumination |
| `manual` | User-provided value | Known threshold from prior experiments |
| `triangle` | `skimage.filters.threshold_triangle()` | Skewed distributions |
| `li` | `skimage.filters.threshold_li()` | Iterative minimum cross-entropy |

## Batch Measurement

```python
class BatchMeasurer:
    """Efficiently measure all regions x all channels."""

    def measure_experiment(self, store: ExperimentStore,
                           channels: list[str] = None,
                           metrics: list[str] = None,
                           progress_callback=None) -> BatchResult:
        """Measure all cells in all regions across all specified channels.

        If channels is None, measures all registered channels.
        If metrics is None, uses all registered metrics.
        """

@dataclass
class BatchResult:
    total_measurements: int
    regions_processed: int
    channels_measured: int
    elapsed_seconds: float
```

## Positive/Negative Classification

After thresholding, cells can be classified as positive or negative:

```python
def classify_cells(self, store: ExperimentStore,
                   channel: str, threshold_run_id: int = None,
                   metric_name: str = "positive_fraction",
                   positive_threshold: float = 0.5) -> int:
    """Classify cells as positive/negative based on threshold mask overlap.

    For each cell:
    1. Read cell mask from label image
    2. Read threshold mask from masks.zarr
    3. Compute overlap fraction
    4. Store as 'positive_fraction' measurement
    5. Tag cell as 'positive_{channel}' or 'negative_{channel}'

    Returns number of cells classified.
    """
```
