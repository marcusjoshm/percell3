# PerCell 3

Single-cell microscopy analysis platform built on OME-Zarr and SQLite.

PerCell 3 replaces PerCell 2's filesystem-based data model with a proper experiment database. It provides a complete pipeline from image import through segmentation, measurement, and data export.

## Architecture

- **ExperimentStore** — Central hub. OME-Zarr for pixel data, SQLite for metadata and measurements.
- **Hexagonal design** — Domain logic has no framework dependencies. External tools (Cellpose, ImageJ, readlif) accessed through adapter interfaces.
- **Channels are first-class** — Segment on DAPI, measure on GFP/RFP. Any operation can target any channel.
- **Plugin system** — Analysis routines read from ExperimentStore and write results back.

## Modules

| Module | Description |
|--------|-------------|
| `core` | ExperimentStore, schema, Zarr I/O |
| `io` | Format readers (LIF, TIFF, CZI) |
| `segment` | Cellpose segmentation engine + ROI import |
| `measure` | Per-cell intensity metrics and thresholding |
| `plugins` | Plugin system + built-in plugins (colocalization, intensity grouping) |
| `workflow` | YAML-based workflow engine |
| `cli` | Click CLI with interactive menu |

## Installation

```bash
pip install -e ".[dev]"
```

Optional extras:

```bash
pip install -e ".[lif]"       # Leica LIF support
pip install -e ".[czi]"       # Zeiss CZI support
pip install -e ".[workflow]"  # YAML workflow engine
pip install -e ".[all]"       # Everything
```

## Usage

### CLI

```bash
# Interactive menu
percell3

# Create a new experiment
percell3 create -d /path/to/experiment -n "My Experiment"

# Import images from a LIF file
percell3 import -e /path/to/experiment.percell -f /path/to/images.lif

# Run segmentation
percell3 segment -e /path/to/experiment.percell -r region1 -c DAPI

# Export measurements
percell3 export -e /path/to/experiment.percell -o results.csv
```

### Python API

```python
from percell3.core import ExperimentStore

store = ExperimentStore("/path/to/experiment.percell")
regions = store.list_regions()
channels = store.list_channels()
```

## Running Tests

```bash
pytest tests/ -v
pytest tests/test_core/ -v           # Test single module
pytest -m "not slow"                 # Skip slow tests (Cellpose model downloads)
```

## Technology Stack

- Python 3.10+
- zarr + ome-zarr (OME-NGFF 0.4)
- SQLite (stdlib sqlite3)
- dask.array for lazy/chunked image access
- cellpose for segmentation
- scikit-image + scipy for image processing
- click + rich for CLI
- pandas for data export

## License

MIT
