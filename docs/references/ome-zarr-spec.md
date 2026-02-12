# OME-NGFF 0.4 — Key Reference

## Specification
Full spec: https://ngff.openmicroscopy.org/0.4/

## Key Points for PerCell 3

### multiscales metadata (required)
Every OME-Zarr group that contains image data must have `multiscales` in `.zattrs`:

```json
{
  "multiscales": [{
    "version": "0.4",
    "axes": [
      {"name": "c", "type": "channel"},
      {"name": "y", "type": "space", "unit": "micrometer"},
      {"name": "x", "type": "space", "unit": "micrometer"}
    ],
    "datasets": [
      {"path": "0", "coordinateTransformations": [{"type": "scale", "scale": [1, 0.65, 0.65]}]}
    ]
  }]
}
```

### Axes
- Required for spatial data: at least "y" and "x" with type "space"
- Channel axis: type "channel" (no unit)
- Z axis: type "space" with unit
- Time axis: type "time" with unit

### coordinateTransformations
- Each dataset (resolution level) needs a `scale` transformation
- Scale values map array indices to physical coordinates
- For channel axis, scale is typically 1.0

### omero metadata (optional but recommended)
```json
{
  "omero": {
    "channels": [
      {"label": "DAPI", "color": "0000FF", "active": true,
       "window": {"start": 0, "end": 65535}}
    ]
  }
}
```

### image-label metadata (for label images)
```json
{
  "image-label": {
    "version": "0.4",
    "source": {"image": "relative/path/to/source/image"}
  }
}
```

## Zarr v2 vs v3
PerCell 3 uses zarr-python v2 API (zarr <3.0). The NGFF 0.4 spec is designed for zarr v2.
When zarr v3 and NGFF 0.5 stabilize, migration will be straightforward.

## napari Compatibility
napari reads OME-Zarr natively via `napari-ome-zarr` plugin:
```
napari my_experiment.percell/images.zarr
```
This works as long as the multiscales metadata is valid.
