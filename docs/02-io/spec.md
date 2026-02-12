# Module 2: IO — Specification

## Overview

The IO module reads microscopy files (LIF, TIFF, CZI) and writes them into an
ExperimentStore. It normalizes vendor-specific metadata into a common model.

## Abstract Base Reader

```python
from abc import ABC, abstractmethod
from pathlib import Path
from percell3.core import ExperimentStore

class BaseReader(ABC):
    """Interface for all format readers."""

    @abstractmethod
    def can_read(self, path: Path) -> bool:
        """Return True if this reader can handle the given file/directory."""

    @abstractmethod
    def read_metadata(self, path: Path) -> ImportMetadata:
        """Extract metadata without reading pixel data.
        Used for preview/confirmation before full import."""

    @abstractmethod
    def import_into(self, path: Path, store: ExperimentStore,
                    condition: str = None,
                    channel_mapping: dict[str, str] = None) -> ImportResult:
        """Import all images from the source into the ExperimentStore.

        Args:
            path: Source file or directory.
            store: Target ExperimentStore.
            condition: Override condition name (default: derived from source).
            channel_mapping: Rename channels during import {"source": "target"}.

        Returns:
            ImportResult with counts and any warnings.
        """
```

## Data Models

```python
@dataclass
class ImportMetadata:
    """Preview of what an import will produce."""
    source_path: Path
    format: str                          # "lif", "tiff_directory", "czi"
    series_count: int                    # Number of images/scenes
    channel_names: list[str]
    pixel_size_um: Optional[float]
    dimensions: dict[str, int]           # {"x": 2048, "y": 2048, "c": 3, ...}
    bit_depth: int
    estimated_size_mb: float

@dataclass
class ImportResult:
    """Summary of a completed import."""
    regions_imported: int
    channels_registered: int
    total_pixels: int
    warnings: list[str]
    elapsed_seconds: float
```

## LIF Reader

Uses the `readlif` library to read Leica Image Format files.

### Behavior
- Each LIF series becomes a separate **region** in the ExperimentStore
- Series name becomes the region name (sanitized)
- Channel names extracted from LIF XML metadata
- Pixel sizes extracted from LIF scale metadata
- Multi-channel images written as a single (C, Y, X) array per region
- If no condition is specified, the LIF filename (without extension) becomes the condition

### Key readlif API
```python
from readlif.reader import LifFile

lif = LifFile("experiment.lif")
for image in lif.get_iter_image():
    name = image.name
    channels = image.channels          # number of channels
    dims = image.dims                  # Dimensions object
    # dims.x, dims.y, dims.z, dims.t, dims.m (mosaic)
    scale = image.scale                # (x_scale, y_scale, z_scale) in meters
    channel_names = [image.get_channel_name(i) for i in range(channels)]

    # Get pixel data for channel c, z-slice z, timepoint t
    frame = image.get_frame(z=0, t=0, c=0)  # returns PIL Image
    arr = np.array(frame)
```

### Edge Cases
- LIF files with mosaic/tiled images: import each tile as separate region
- LIF files with Z-stacks: write as (C, Z, Y, X) array
- LIF files with timelapse: one region per timepoint (using timepoints table)
- Channel names may be empty in some LIF files: fall back to "Channel_0", "Channel_1"

## TIFF Directory Reader

Reads PerCell 2's directory layout:

```
experiment_dir/
├── condition_1/
│   ├── region_1/
│   │   ├── DAPI.tif
│   │   ├── GFP.tif
│   │   └── RFP.tif
│   └── region_2/
└── condition_2/
```

### Behavior
- Top-level directories become **conditions**
- Second-level directories become **regions**
- TIFF files within each region directory become **channels** (filename = channel name)
- If a timepoint level exists (3 directory levels), the middle level becomes timepoints
- Pixel size read from TIFF metadata if available, otherwise user must specify
- Handles both single-page and multi-page TIFFs

### TIFF Metadata Extraction
```python
import tifffile
with tifffile.TiffFile("image.tif") as tif:
    page = tif.pages[0]
    # Try to extract pixel size from various metadata sources:
    # 1. OME-XML (if OME-TIFF)
    # 2. ImageJ metadata
    # 3. TIFF resolution tags
    # 4. Fall back to None (user provides)
```

## CZI Reader (Optional)

Uses `aicspylibczi` for Carl Zeiss Image files. Similar pattern to LIF reader.
This is an optional dependency — the reader gracefully degrades if not installed.

## Dtype Handling

| Source | Stored As | Notes |
|--------|-----------|-------|
| 8-bit unsigned | uint8 | Direct copy |
| 12-bit (packed in 16) | uint16 | Common in LIF files, preserve as uint16 |
| 16-bit unsigned | uint16 | Direct copy |
| 32-bit float | float32 | For processed images |

## Import Progress

Readers should support progress callbacks for the CLI to display progress bars:

```python
def import_into(self, path, store, progress_callback=None, ...):
    for i, region in enumerate(regions):
        # ... import region ...
        if progress_callback:
            progress_callback(current=i+1, total=len(regions), region=region.name)
```
