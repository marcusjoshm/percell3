# Background Subtraction Plugin for percell3 — Claude Code Prompt

## Context

percell3 stores microscopy data as OME-Zarr files. Each FOV has channel image layers, a segmentation layer (integer labels identifying individual cells), and one or more threshold layers (binary masks produced by GMM cell grouping + Otsu thresholding). A configuration layer in the DB associates each FOV with exactly one segmentation layer and any number of named threshold layers (e.g. `threshold_g1`, `threshold_g2`). The plugin system allows analysis routines to read from and write back to `ExperimentStore`.

## Goal

Create a new plugin called `BackgroundSubtractionPlugin` (file: `src/percell3/plugins/background_subtraction.py`) that performs per-threshold-layer background subtraction and produces derived FOVs as new DB records with new zarr arrays.

---

## Plugin Logic

### Step 1 — User inputs (via interactive CLI menu, consistent with existing menu style)

1. Display only FOVs that have at least one threshold layer configured. Let the user multi-select from this list.
2. Let the user select a single channel to operate on.

### Step 2 — Per FOV: generate one histogram per configured threshold layer

For each selected FOV and each of its configured threshold layers:

1. Load the channel image array for the selected channel.
2. Load the binary mask array for the threshold layer.
3. Extract all pixel intensities from the channel image where the threshold mask is `True`. These are the only pixels used — do not use raw segmentation labels directly.
4. Compute the background value using the following logic (port directly from the reference function `find_gaussian_peaks` below):
   - Filter out zero-valued pixels from the extracted intensity array.
   - If no non-zero pixels remain, skip this threshold layer with a warning.
   - Build a 50-bin histogram over `(0, max_value)`.
   - Smooth with a 1D Gaussian filter, sigma=2.
   - Detect peaks using `scipy.signal.find_peaks` with a minimum prominence of 15% of the smoothed histogram's maximum.
   - If no peaks are found, fall back to `argmax` of the smoothed histogram.
   - If peaks are found, sort by prominence descending. The **most prominent peak's bin center** is the background value.

### Step 3 — Create derived FOVs

For each (source FOV, threshold layer, background value) triple:

1. Create a new full-frame numpy array (same shape as the source channel image) initialized to zeros, with the same dtype as the source channel (or float32 if subtraction would underflow).
2. Where the threshold mask is `True`, write: `max(0, original_pixel_value - background_value)` (i.e. subtract and clip at zero — no negative values).
3. All pixels outside the threshold mask remain zero.
4. Register a new FOV record in the DB. Suggested naming convention: `{source_fov_name}_bgsub_{threshold_layer_name}_{channel_name}`. Ensure the name is unique; append a numeric suffix if a collision exists.
5. Write the derived array as a new zarr array in the appropriate zarr store, linked to the new FOV record.
6. Write a provenance record to the DB (new table or metadata field) containing:
   - `source_fov_id`
   - `threshold_layer_name`
   - `channel_name`
   - `background_value` (float)
   - `plugin_name`: `"background_subtraction"`
   - `created_at` timestamp

### Step 4 — Reporting

After all FOVs are processed, print a summary table (using `rich`) showing: source FOV, threshold layer, channel, background value used, and derived FOV name created.

---

## Reference: `find_gaussian_peaks` logic to port

```python
from scipy.ndimage import gaussian_filter1d
from scipy.signal import find_peaks
import numpy as np

def find_gaussian_peaks(data, n_bins=50):
    data = data[data > 0]
    if len(data) == 0:
        return None
    data_max = float(np.max(data))
    if data_max == 0:
        return None
    hist, bin_edges = np.histogram(data, bins=n_bins, range=(0, data_max))
    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
    hist_smooth = gaussian_filter1d(hist.astype(float), sigma=2)
    min_prominence = np.max(hist_smooth) * 0.15
    peaks, properties = find_peaks(hist_smooth, prominence=min_prominence)
    if len(peaks) == 0:
        peak_idx = np.argmax(hist_smooth)
        bg_value = float(bin_centers[peak_idx])
        return {"background_value": bg_value, "n_peaks": 1}
    prominences = properties["prominences"]
    sorted_idx = np.argsort(prominences)[::-1]
    bg_value = float(bin_centers[peaks[sorted_idx[0]]])
    return {"background_value": bg_value, "n_peaks": len(peaks)}
```

---

## Implementation Notes

- Follow the existing plugin interface/base class pattern in `src/percell3/plugins/`.
- Follow existing patterns in `ExperimentStore` for registering new FOVs and writing zarr arrays — do not bypass the store's API.
- The derived FOV should be queryable and viewable via the existing napari viewer and export commands (it is a real FOV in the DB, just with a single channel array).
- Add a menu entry for this plugin consistent with the existing interactive CLI menu style.
- Use `rich` for progress display during processing.
- Handle edge cases: FOVs with no threshold layers configured should not appear in the selection list; threshold layers that yield no non-zero pixels after masking should be skipped with a clear warning message.

---

## Open Question to Resolve Before Implementation

**Does the derived FOV need to carry over metadata from the source FOV** (condition, bio rep, pixel size), or should it stand alone with just its own name and the provenance record? This will determine what fields need to be populated in the new FOV DB record.
