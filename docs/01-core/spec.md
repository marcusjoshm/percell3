# Module 1: Core — Specification

## Overview

The core module provides `ExperimentStore`, the central object that all other modules interact with. It wraps a `.percell` directory containing a SQLite database and OME-Zarr stores.

## ExperimentStore Public API

```python
class ExperimentStore:
    """Central interface for a PerCell 3 experiment."""

    # --- Lifecycle ---
    @classmethod
    def create(cls, path: Path, name: str = "", description: str = "") -> "ExperimentStore":
        """Create a new .percell experiment directory."""

    @classmethod
    def open(cls, path: Path) -> "ExperimentStore":
        """Open an existing .percell experiment directory."""

    def close(self) -> None:
        """Close database connections and flush pending writes."""

    def __enter__(self) -> "ExperimentStore": ...
    def __exit__(self, *args) -> None: ...

    # --- Channel Management ---
    def add_channel(self, name: str, role: str = None, color: str = None,
                    excitation_nm: float = None, emission_nm: float = None) -> int:
        """Register a channel. Returns channel ID."""

    def get_channels(self) -> list[ChannelConfig]:
        """List all registered channels."""

    def get_channel(self, name: str) -> ChannelConfig:
        """Get channel config by name. Raises KeyError if not found."""

    # --- Condition/Timepoint/Region Management ---
    def add_condition(self, name: str, description: str = "") -> int:
    def add_timepoint(self, name: str, time_seconds: float = None) -> int:
    def add_region(self, name: str, condition: str, timepoint: str = None,
                   width: int = None, height: int = None,
                   pixel_size_um: float = None, source_file: str = None) -> int:

    def get_conditions(self) -> list[str]:
    def get_timepoints(self) -> list[str]:
    def get_regions(self, condition: str = None, timepoint: str = None) -> list[RegionInfo]:

    # --- Image I/O (OME-Zarr) ---
    def write_image(self, region: str, condition: str, channel: str,
                    data: np.ndarray, timepoint: str = None) -> None:
        """Write a 2D/3D image array to the OME-Zarr store."""

    def read_image(self, region: str, condition: str, channel: str,
                   timepoint: str = None) -> da.Array:
        """Read an image as a lazy dask array from OME-Zarr."""

    def read_image_numpy(self, region: str, condition: str, channel: str,
                         timepoint: str = None) -> np.ndarray:
        """Read an image fully into memory as numpy array."""

    # --- Label Images (Segmentation Results) ---
    def write_labels(self, region: str, condition: str, labels: np.ndarray,
                     segmentation_run_id: int, timepoint: str = None) -> None:
        """Write a segmentation label image to labels.zarr."""

    def read_labels(self, region: str, condition: str,
                    segmentation_run_id: int = None, timepoint: str = None) -> np.ndarray:
        """Read a label image. If segmentation_run_id is None, use the latest."""

    # --- Cell Records ---
    def add_cells(self, cells: list[CellRecord]) -> list[int]:
        """Bulk insert cell records. Returns list of cell IDs."""

    def get_cells(self, condition: str = None, region: str = None,
                  timepoint: str = None, is_valid: bool = True,
                  min_area: float = None, max_area: float = None,
                  tags: list[str] = None) -> pd.DataFrame:
        """Query cells with flexible filters. Returns DataFrame."""

    def get_cell_count(self, **filters) -> int:
        """Count cells matching filters."""

    # --- Measurements ---
    def add_measurements(self, measurements: list[MeasurementRecord]) -> None:
        """Bulk insert measurements."""

    def get_measurements(self, cell_ids: list[int] = None,
                         channels: list[str] = None,
                         metrics: list[str] = None) -> pd.DataFrame:
        """Query measurements. Returns DataFrame with columns:
        cell_id, channel, metric, value."""

    def get_measurement_pivot(self, channels: list[str] = None,
                              metrics: list[str] = None,
                              include_cell_info: bool = True) -> pd.DataFrame:
        """Get measurements as a pivot table: one row per cell,
        columns like 'GFP_mean_intensity', 'RFP_max_intensity'."""

    # --- Masks ---
    def write_mask(self, region: str, condition: str, channel: str,
                   mask: np.ndarray, threshold_run_id: int,
                   timepoint: str = None) -> None:
        """Write a binary mask to masks.zarr."""

    def read_mask(self, region: str, condition: str, channel: str,
                  threshold_run_id: int = None, timepoint: str = None) -> np.ndarray:
        """Read a binary mask."""

    # --- Segmentation Runs ---
    def add_segmentation_run(self, channel: str, model_name: str,
                             parameters: dict = None) -> int:
        """Log a segmentation run. Returns run ID."""

    # --- Threshold Runs ---
    def add_threshold_run(self, channel: str, method: str,
                          parameters: dict = None) -> int:
        """Log a thresholding run. Returns run ID."""

    # --- Analysis Runs ---
    def start_analysis_run(self, plugin_name: str, parameters: dict = None) -> int:
        """Start tracking an analysis run. Returns run ID."""

    def complete_analysis_run(self, run_id: int, status: str = "completed",
                              cell_count: int = None) -> None:
        """Mark an analysis run as completed or failed."""

    # --- Tags ---
    def add_tag(self, name: str, color: str = None) -> int:
    def tag_cells(self, cell_ids: list[int], tag: str) -> None:
    def untag_cells(self, cell_ids: list[int], tag: str) -> None:

    # --- Export ---
    def export_csv(self, path: Path, channels: list[str] = None,
                   metrics: list[str] = None, **cell_filters) -> None:
        """Export measurements as a CSV file."""

    # --- Properties ---
    @property
    def path(self) -> Path:
        """Path to the .percell directory."""

    @property
    def name(self) -> str:
    @property
    def db_path(self) -> Path:
    @property
    def images_zarr_path(self) -> Path:
    @property
    def labels_zarr_path(self) -> Path:
    @property
    def masks_zarr_path(self) -> Path:
```

## Data Models

```python
@dataclass
class ChannelConfig:
    id: int
    name: str
    role: Optional[str] = None          # "nucleus", "signal", "membrane", etc.
    excitation_nm: Optional[float] = None
    emission_nm: Optional[float] = None
    color: Optional[str] = None         # hex color "#0000FF"
    is_segmentation: bool = False

@dataclass
class RegionInfo:
    id: int
    name: str
    condition: str
    timepoint: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    pixel_size_um: Optional[float] = None
    source_file: Optional[str] = None

@dataclass
class CellRecord:
    region_id: int
    segmentation_id: int
    label_value: int                    # pixel value in label image
    centroid_x: float
    centroid_y: float
    bbox_x: int
    bbox_y: int
    bbox_w: int
    bbox_h: int
    area_pixels: float
    area_um2: Optional[float] = None
    perimeter: Optional[float] = None
    circularity: Optional[float] = None

@dataclass
class MeasurementRecord:
    cell_id: int
    channel_id: int
    metric: str                         # "mean_intensity", "max_intensity", etc.
    value: float
```

## Error Handling

- `ExperimentError` base exception for all experiment-related errors
- `ExperimentNotFoundError` when opening nonexistent .percell directory
- `ChannelNotFoundError` when referencing undefined channel
- `RegionNotFoundError` when referencing undefined region
- `DuplicateError` when adding duplicate channels/conditions/cells
