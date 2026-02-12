# OME-Zarr Layout — PerCell 3

## .percell Directory Structure

```
my_experiment.percell/
├── experiment.db                           # SQLite database
│
├── images.zarr/                            # Raw image data (OME-Zarr)
│   ├── .zgroup
│   ├── .zattrs                             # {"percell_version": "3.0.0"}
│   │
│   ├── condition_1/
│   │   ├── .zgroup
│   │   ├── timepoint_1/                    # (omitted if no timepoints)
│   │   │   ├── .zgroup
│   │   │   ├── region_1/                   # One OME-Zarr image per region
│   │   │   │   ├── .zgroup
│   │   │   │   ├── .zattrs                 # NGFF multiscales metadata
│   │   │   │   ├── 0/                      # Full resolution: shape (C, Y, X)
│   │   │   │   │   ├── .zarray
│   │   │   │   │   └── <chunk files>
│   │   │   │   └── 1/                      # 2x downsampled (optional pyramid)
│   │   │   │       ├── .zarray
│   │   │   │       └── <chunk files>
│   │   │   └── region_2/
│   │   └── timepoint_2/
│   └── condition_2/
│
├── labels.zarr/                            # Segmentation label images
│   ├── .zgroup
│   ├── condition_1/
│   │   └── timepoint_1/
│   │       └── region_1/
│   │           ├── .zgroup
│   │           ├── .zattrs                 # NGFF labels metadata
│   │           └── 0/                      # Shape (Y, X), dtype int32
│   │               ├── .zarray
│   │               └── <chunk files>
│
└── masks.zarr/                             # Binary analysis masks
    ├── .zgroup
    ├── condition_1/
    │   └── timepoint_1/
    │       └── region_1/
    │           ├── threshold_GFP/          # One mask per threshold run
    │           │   ├── .zgroup
    │           │   ├── .zattrs
    │           │   └── 0/                  # Shape (Y, X), dtype bool/uint8
    │           └── threshold_RFP/
```

## NGFF 0.4 Metadata Format

Each region's `.zattrs` must contain valid NGFF `multiscales` metadata:

```json
{
  "multiscales": [
    {
      "version": "0.4",
      "name": "region_1",
      "axes": [
        {"name": "c", "type": "channel"},
        {"name": "y", "type": "space", "unit": "micrometer"},
        {"name": "x", "type": "space", "unit": "micrometer"}
      ],
      "datasets": [
        {
          "path": "0",
          "coordinateTransformations": [
            {"type": "scale", "scale": [1.0, 0.65, 0.65]}
          ]
        }
      ],
      "coordinateTransformations": [
        {"type": "identity"}
      ]
    }
  ],
  "omero": {
    "channels": [
      {"label": "DAPI", "color": "0000FF", "active": true, "window": {"start": 0, "end": 65535}},
      {"label": "GFP", "color": "00FF00", "active": true, "window": {"start": 0, "end": 65535}},
      {"label": "RFP", "color": "FF0000", "active": true, "window": {"start": 0, "end": 65535}}
    ]
  }
}
```

## Label Image Metadata

Labels use the NGFF `image-label` spec:

```json
{
  "image-label": {
    "version": "0.4",
    "source": {
      "image": "../../images.zarr/condition_1/timepoint_1/region_1"
    }
  },
  "multiscales": [
    {
      "version": "0.4",
      "axes": [
        {"name": "y", "type": "space", "unit": "micrometer"},
        {"name": "x", "type": "space", "unit": "micrometer"}
      ],
      "datasets": [
        {"path": "0", "coordinateTransformations": [{"type": "scale", "scale": [0.65, 0.65]}]}
      ]
    }
  ]
}
```

## Chunking Strategy

| Data Type | Typical Size | Chunk Shape | Compression |
|-----------|-------------|-------------|-------------|
| Raw images (CYX) | 3x2048x2048 | (1, 512, 512) | Blosc(lz4, level=5) |
| Raw images (CZYX) | 3x50x2048x2048 | (1, 10, 512, 512) | Blosc(lz4, level=5) |
| Label images (YX) | 2048x2048 | (512, 512) | Blosc(lz4, level=5) |
| Binary masks (YX) | 2048x2048 | (512, 512) | Blosc(zstd, level=3) |

## Key Implementation Notes

- Channel dimension is ALWAYS the first array dimension (C, Y, X) or (C, Z, Y, X)
- Each channel is stored in the same array, NOT as separate Zarr groups
- Label images are integer-typed (int32) where pixel value = cell ID (0 = background)
- Masks are uint8 (0 or 255) for compatibility with ImageJ and napari
- The zarr_path stored in SQLite regions table is relative to the .percell directory
- Use `zarr.open(path, mode='a')` for append-safe access
- Pyramid levels are optional but recommended for images > 4096 in any dimension
