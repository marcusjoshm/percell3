# Module 3: Segment — Specification

## Overview

The segmentation module runs cell segmentation on images from the ExperimentStore,
stores integer label images in OME-Zarr, and populates the cells table in SQLite.
It's decoupled from any specific segmentation tool via an abstract interface.

## Abstract Segmenter Interface

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class SegmentationParams:
    """Parameters for a segmentation run."""
    channel: str                         # Which channel to segment
    model_name: str = "cyto3"            # Cellpose model name
    diameter: Optional[float] = None     # Cell diameter in pixels (None = auto)
    flow_threshold: float = 0.4
    cellprob_threshold: float = 0.0
    gpu: bool = True
    min_size: int = 15                   # Minimum cell area in pixels
    normalize: bool = True
    channels_cellpose: list[int] = None  # Cellpose channel config [cyto, nucleus]

class BaseSegmenter(ABC):
    """Interface for segmentation backends."""

    @abstractmethod
    def segment(self, image: np.ndarray, params: SegmentationParams) -> np.ndarray:
        """Run segmentation on a 2D image.

        Args:
            image: 2D array (Y, X) of the channel to segment.
            params: Segmentation parameters.

        Returns:
            Label image (Y, X) where pixel value = cell ID, 0 = background.
        """

    @abstractmethod
    def segment_batch(self, images: list[np.ndarray],
                      params: SegmentationParams) -> list[np.ndarray]:
        """Run segmentation on multiple images (for GPU batching)."""
```

## Cellpose Adapter

```python
class CellposeAdapter(BaseSegmenter):
    """Wraps the Cellpose library."""

    def __init__(self):
        from cellpose import models
        self._model_cache: dict[str, models.Cellpose] = {}

    def segment(self, image, params):
        model = self._get_model(params.model_name, params.gpu)
        masks, flows, styles, diams = model.eval(
            image,
            diameter=params.diameter,
            flow_threshold=params.flow_threshold,
            cellprob_threshold=params.cellprob_threshold,
            min_size=params.min_size,
            normalize=params.normalize,
            channels=params.channels_cellpose or [0, 0],
        )
        return masks.astype(np.int32)
```

## Label Processor

Converts a label image into `CellRecord` objects using scikit-image `regionprops`:

```python
class LabelProcessor:
    """Extract cell properties from a label image."""

    def extract_cells(self, labels: np.ndarray, region_id: int,
                      segmentation_id: int,
                      pixel_size_um: float = None) -> list[CellRecord]:
        """Convert label image to CellRecord list.

        Uses skimage.measure.regionprops to compute:
        - centroid (x, y)
        - bounding box (x, y, w, h)
        - area (pixels and um^2 if pixel_size provided)
        - perimeter
        - circularity (4 * pi * area / perimeter^2)
        """
```

### Properties Extracted

| Property | Source | Stored In |
|----------|--------|-----------|
| label_value | regionprop.label | cells.label_value |
| centroid_x, centroid_y | regionprop.centroid (reversed for x,y) | cells.centroid_x/y |
| bbox_x, bbox_y, bbox_w, bbox_h | regionprop.bbox | cells.bbox_* |
| area_pixels | regionprop.area | cells.area_pixels |
| area_um2 | area_pixels * pixel_size^2 | cells.area_um2 |
| perimeter | regionprop.perimeter | cells.perimeter |
| circularity | 4*pi*area/perimeter^2 | cells.circularity |

## Segmentation Pipeline

The high-level segmentation flow:

```python
def segment_experiment(store: ExperimentStore, params: SegmentationParams,
                       segmenter: BaseSegmenter = None,
                       regions: list[str] = None,
                       progress_callback=None) -> int:
    """Run segmentation on an experiment.

    1. Log segmentation run in SQLite
    2. For each region:
       a. Read the target channel from images.zarr
       b. Run segmentation -> label image
       c. Write label image to labels.zarr
       d. Extract cell properties from label image
       e. Insert CellRecords into SQLite
    3. Update segmentation run with cell count
    4. Return segmentation run ID
    """
```

## ROI Import

Support importing pre-existing segmentations:

```python
class RoiImporter:
    """Import label images from external sources."""

    def import_labels(self, labels: np.ndarray, store: ExperimentStore,
                      region: str, condition: str,
                      source: str = "manual") -> int:
        """Import a pre-computed label image.
        Creates a segmentation run and extracts cell records."""

    def import_imagej_rois(self, roi_path: Path, image_shape: tuple,
                           store: ExperimentStore,
                           region: str, condition: str) -> int:
        """Import ImageJ ROI zip file as label image."""
```

## Edge Cases
- Images with no cells detected: log warning, store empty label image, cell_count = 0
- Very large images (>4096 px): process in tiles if memory constrained
- Overlapping cells in Cellpose output: Cellpose handles this internally (no overlap in masks)
- Re-segmentation of same region: creates new segmentation_run, does not delete old cells
