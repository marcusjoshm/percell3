---
title: "feat: Add background subtraction plugin"
type: feat
date: 2026-03-04
deepened: 2026-03-04
brainstorm: docs/brainstorms/2026-03-04-background-subtraction-plugin-brainstorm.md
---

# feat: Add Background Subtraction Plugin

## Enhancement Summary

**Deepened on:** 2026-03-04
**Agents used:** kieran-python-reviewer, performance-oracle, architecture-strategist, code-simplicity-reviewer, pattern-recognition-specialist, best-practices-researcher, learnings-researcher

### Key Improvements
1. Fixed critical integer underflow bug in subtraction expression (silent data corruption)
2. Resolved peak detection code duplication with existing `bg_subtraction_core.py`
3. Renamed plugin to avoid collision with existing `local_bg_subtraction`
4. Reordered CLI flow to match established channel-first, FOV-second pattern
5. Added performance optimizations (image caching, matplotlib leak prevention)

### Critical Findings from Review
- `np.clip(image - bg_value, 0, None)` silently wraps on uint16 — must cast to int32 first
- `estimate_background_gaussian()` already exists in `bg_subtraction_core.py` — extract to shared module, don't duplicate
- Plugin name "background_subtraction" collides with existing "local_bg_subtraction"

---

## Overview

Create a `ThresholdBGSubtractionPlugin` that estimates per-threshold-layer background intensity via histogram peak detection and produces derived FOVs with background-subtracted images. Follows the established plugin pattern (Image Calculator / Split-Halo).

## Problem Statement

Users need to subtract spatially-varying background from fluorescence microscopy images before downstream quantification. The background level differs per threshold group (cell subpopulation), so subtraction must be done per-threshold-layer using only the masked pixels to estimate background.

## Proposed Solution

Two new files + one refactor + one menu.py modification:

1. **`src/percell3/plugins/builtin/peak_detection.py`** — Extract `estimate_background_gaussian` from `bg_subtraction_core.py` into shared module; add `PeakDetectionResult` dataclass and `render_peak_histogram` helper
2. **`src/percell3/plugins/builtin/threshold_bg_subtraction.py`** — AnalysisPlugin subclass
3. **Refactor `bg_subtraction_core.py`** — Import from `peak_detection.py` instead of duplicating the algorithm
4. Menu handler added to **`src/percell3/cli/menu.py`**

## Technical Approach

### Phase 1: Shared Peak Detection Module

**File:** `src/percell3/plugins/builtin/peak_detection.py`

Extract `estimate_background_gaussian` from `bg_subtraction_core.py` (lines 48-144) into this shared module. The existing function already implements the exact algorithm needed. Add a typed return dataclass.

```python
# peak_detection.py
from dataclasses import dataclass, field
import numpy as np
import numpy.typing as npt

@dataclass(frozen=True, slots=True)
class PeakDetectionResult:
    """Result of histogram-based background estimation."""
    background_value: float
    n_peaks: int
    hist: npt.NDArray[np.float64]
    bin_centers: npt.NDArray[np.float64]
    hist_smooth: npt.NDArray[np.float64]
    peak_indices: npt.NDArray[np.intp]


def find_gaussian_peaks(
    data: npt.NDArray[np.number],
    n_bins: int = 50,
    sigma: float = 2.0,
    min_prominence_frac: float = 0.15,
) -> PeakDetectionResult | None:
    """Estimate background value from intensity histogram peak detection.

    Args:
        data: 1D array of pixel intensities (zeros are filtered out internally).
        n_bins: Number of histogram bins.
        sigma: Gaussian smoothing sigma for the histogram.
        min_prominence_frac: Minimum peak prominence as fraction of max.

    Returns:
        PeakDetectionResult with background_value and histogram data for
        diagnostic plotting, or None if no valid data.
    """
```

### Research Insights: Peak Detection

**Integer underflow prevention (CRITICAL):**
The subtraction `image - bg_value` silently wraps on unsigned dtypes. Must cast to signed type first:
```python
# WRONG — silent data corruption on uint8/uint16:
np.clip(image - bg_value, 0, None).astype(image.dtype)

# CORRECT:
result = np.clip(image.astype(np.int32) - int(bg_value), 0, np.iinfo(image.dtype).max)
result = result.astype(image.dtype)
```

**Histogram binning considerations:**
- 50 bins is appropriate for typical fluorescence data (intensity range 0-500, bin width ~10)
- Risk: if data contains saturated pixels (65535 for 16-bit), range stretches and bins become too coarse (width ~1310)
- Mitigation: exclude saturated pixels before histogramming, or use percentile-based range
- The 15% prominence threshold is a defensible default for background estimation

**Matplotlib rendering helper:**
Extract histogram PNG rendering into `peak_detection.py` to keep it testable without a store:
```python
def render_peak_histogram(
    result: PeakDetectionResult,
    title: str,
    output_path: Path,
) -> None:
    """Save diagnostic histogram PNG showing detected background peak."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6, 4))
    try:
        bin_width = result.bin_centers[1] - result.bin_centers[0] if len(result.bin_centers) > 1 else 1.0
        ax.bar(result.bin_centers, result.hist, width=bin_width, alpha=0.5, label="Raw")
        ax.plot(result.bin_centers, result.hist_smooth, 'r-', label="Smoothed")
        ax.axvline(result.background_value, color='green', linestyle='--',
                   label=f"BG={result.background_value:.1f}")
        ax.set_xlabel("Intensity")
        ax.set_ylabel("Count")
        ax.set_title(title)
        ax.legend()
        fig.savefig(output_path, dpi=100, bbox_inches="tight")
    finally:
        plt.close(fig)  # CRITICAL: prevents memory leak in loops
```

**Refactor `bg_subtraction_core.py`:**
After extracting, update `bg_subtraction_core.py` to import from `peak_detection`:
```python
from percell3.plugins.builtin.peak_detection import find_gaussian_peaks, PeakDetectionResult
```
This eliminates the duplicate implementation. Both `local_bg_subtraction` and `split_halo_condensate_analysis` already import from `bg_subtraction_core`, so the transitive dependency chain stays stable.

### Phase 2: Plugin Class

**File:** `src/percell3/plugins/builtin/threshold_bg_subtraction.py`

```python
class ThresholdBGSubtractionPlugin(AnalysisPlugin):
    def info(self) -> PluginInfo:
        # name="threshold_bg_subtraction", version="1.0.0"
        # Description: "Per-threshold-layer histogram-based background subtraction"

    def required_inputs(self) -> list[PluginInputRequirement]:
        # [PluginInputRequirement(kind=InputKind.THRESHOLD)]
        # Note: no SEGMENTATION required — operates on threshold masks directly

    def validate(self, store: ExperimentStore) -> list[str]:
        # Check: at least one threshold exists, at least one channel exists

    def get_parameter_schema(self) -> dict[str, Any]:
        # Required: channel (str), fov_ids (list[int])

    def run(
        self,
        store: ExperimentStore,
        cell_ids: list[int] | None = None,
        parameters: dict[str, Any] | None = None,
        progress_callback: Any | None = None,
    ) -> PluginResult:
        # Main processing loop — decomposed into private methods
```

**`run()` method — decomposed into private methods for testability:**

```
1. Extract parameters: channel, fov_ids
2. Build fov_name_to_id = {f.display_name: f.id for f in store.get_fovs()}
3. Create exports/bgsub_histograms/ directory
4. For each fov_id in fov_ids:
   a. self._process_fov(store, fov_id, channel, fov_name_to_id, ...)

_process_fov(store, fov_id, channel, fov_name_to_id, ...):
   a. Get fov_info via store.get_fov_by_id(fov_id)
   b. Load channel image ONCE: store.read_image_numpy(fov_id, channel)
   c. Get fov_config entries, filter to non-null threshold_id
   d. For each threshold entry:
      self._process_threshold(store, fov_info, channel_image, threshold_info, ...)

_process_threshold(store, fov_info, channel_image, threshold_info, ...):
   i.   Load mask: store.read_mask(threshold_id)
   ii.  mask_bool = mask > 0  (mask is 0/255 uint8)
   iii. Extract masked pixels: channel_image[mask_bool]
   iv.  Call find_gaussian_peaks(masked_pixels)
   v.   If None → add warning, return
   vi.  Build derived image (SAFE unsigned subtraction):
        subtracted = np.clip(
            channel_image.astype(np.int32) - int(bg_value),
            0, np.iinfo(channel_image.dtype).max
        )
        derived = np.where(mask_bool, subtracted, 0).astype(channel_image.dtype)
   vii. Derive FOV name: f"{fov_name}_bgsub_{threshold_name}_{channel}"
   viii. Check fov_name_to_id for idempotent reuse
   ix.  store.add_fov(condition=..., bio_rep=..., display_name=...,
                      width=..., height=..., pixel_size_um=...)
   x.   store.write_image(derived_fov_id, channel, derived)
   xi.  render_peak_histogram(result, title, output_path)
   xii. Track result for summary
```

### Research Insights: Plugin Implementation

**Performance — cache channel image per FOV:**
The same channel image is needed for every threshold of a given FOV. Load it once in `_process_fov` and pass it to `_process_threshold`. For 5 thresholds on a 2048x2048 uint16 image, this saves 4 redundant 8MB reads per FOV.

**Memory — `np.where` intermediate allocation:**
The `np.where(mask_bool, subtracted, 0)` with Python int `0` creates an int64 intermediate. Use a typed zero to avoid 4x memory overhead:
```python
np.where(mask_bool, subtracted, channel_image.dtype.type(0))
```

**Derived FOV writes only the processed channel:**
This is correct for this use case — other channels have no meaning in a background-subtracted context. Differs from split_halo (which writes all channels masked) but is intentional. Downstream workflows must handle FOVs with partial channel data gracefully.

**Histogram PNG timestamps:**
Add timestamp to match CSV export convention, preventing silent overwrites:
```python
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
filename = f"{fov_name}_{threshold_name}_{channel}_{timestamp}.png"
```

### Phase 3: CLI Menu Handler

**File:** `src/percell3/cli/menu.py`

Add `_run_threshold_bg_subtraction(state, registry)` function and wire into `_make_plugin_runner`.

**Interactive flow (channel-first, FOV-second — matching existing pattern):**

```
Step 1: Validate plugin (abort with errors if fails)
Step 2: Get channels, single-select via numbered_select_one()
Step 3: Get all FOVs, filter to those with at least one threshold in fov_config
        Show FOV status table, multi-select via _select_fovs_from_table()
Step 4: Print confirmation summary (channel, FOV count, "all configured thresholds")
Step 5: Yes/No confirmation prompt: numbered_select_one(["Yes", "No"], "\nProceed?")
Step 6: Run plugin with progress bar via make_progress()
Step 7: Print rich summary table:
        | Source FOV | Threshold | Channel | BG Value | Derived FOV |
Step 8: Print histogram export path, warnings
```

**Wiring** — add to `_make_plugin_runner` (line ~377):

```python
elif plugin_name == "threshold_bg_subtraction":
    _run_threshold_bg_subtraction(state, registry)
```

### Research Insights: CLI Handler

**Step ordering matters:** Existing handlers (`_run_bg_subtraction`, `_run_condensate_analysis`) both prompt for channel/parameters first, then FOV selection. This lets users configure the analysis before choosing which data to apply it to.

**Confirmation prompt is required:** Both existing custom handlers have `numbered_select_one(["Yes", "No"], "\nProceed?")` before execution. The original plan omitted this.

**Lazy imports:** In `menu.py`, import the plugin handler lazily inside the function, not at module top level. This keeps `percell3 --help` fast.

## Acceptance Criteria

- [x] `find_gaussian_peaks()` in `peak_detection.py` matches reference implementation behavior
- [x] `bg_subtraction_core.py` refactored to import from `peak_detection.py` (no duplication)
- [x] Existing tests for `local_bg_subtraction` and `split_halo` still pass after refactor
- [x] Plugin discovers automatically via `PluginRegistry.discover()`
- [x] FOV selection filters to only FOVs with configured thresholds
- [x] Each FOV x threshold combo produces one derived FOV
- [x] Derived FOV inherits condition, bio_rep, pixel_size_um, timepoint from source
- [ ] Derived FOV gets whole_field segmentation + fov_config (full citizen)
- [x] Output dtype matches source dtype, values clipped at zero via int32 intermediate
- [x] Pixels outside threshold mask are zero in derived image
- [x] Idempotent: re-running with same params overwrites existing derived FOVs
- [x] Histogram PNG saved per FOV/threshold combo to `exports/bgsub_histograms/`
- [x] Rich summary table printed after processing
- [x] Skipped threshold layers (no non-zero pixels) produce warnings, not errors
- [x] Plugin appears in Plugins menu with custom interactive handler
- [x] CLI handler includes Yes/No confirmation before execution

## Edge Cases

| Case | Behavior |
|---|---|
| FOV has no threshold layers in fov_config | Excluded from selection list |
| Threshold mask has no non-zero pixels | Skip with warning in PluginResult.warnings |
| All masked pixels are zero intensity | `find_gaussian_peaks` returns None -> skip with warning |
| Derived FOV name already exists (re-run) | Reuse existing FOV ID, overwrite image data |
| Name collision from different source | Reuse existing FOV ID (same as split_halo/image_calculator pattern) |
| Single FOV in experiment | Auto-select it (numbered_select_one behavior) |
| Single channel in experiment | Auto-select it |
| bg_value > max pixel value | All subtracted pixels become 0 -- valid but add info-level note |
| Saturated pixels (65535 for uint16) | Included in histogram; consider filtering in future iteration |
| Very few masked pixels (< 30) | Peak detection may be noisy; add warning if < 30 pixels |

## Implementation Order

1. `peak_detection.py` -- extract from `bg_subtraction_core.py`, add `PeakDetectionResult` dataclass and `render_peak_histogram`
2. Refactor `bg_subtraction_core.py` -- import from `peak_detection.py`, verify existing tests pass
3. `threshold_bg_subtraction.py` -- plugin class using peak_detection
4. `menu.py` -- CLI handler wiring
5. Tests for peak_detection (unit) and plugin (integration)

## Testing

### Unit Tests: `tests/test_plugins/test_peak_detection.py`

```python
# Test cases for find_gaussian_peaks():
- Single clear peak -> returns correct bin center as PeakDetectionResult
- Two peaks with different prominences -> returns most prominent
- All-zero data -> returns None
- Single non-zero value -> returns that value's bin
- Uniform distribution -> returns argmax of smoothed histogram
- Verify PeakDetectionResult fields are all populated (hist, bin_centers, hist_smooth, peak_indices)

# Test cases for render_peak_histogram():
- Produces PNG file at specified path
- Handles PeakDetectionResult with single peak
- Handles PeakDetectionResult with multiple peaks
```

### Regression Tests: `tests/test_plugins/test_bg_subtraction_core.py`

```python
# After refactoring bg_subtraction_core to import from peak_detection:
- All existing estimate_background_gaussian tests still pass
- All existing process_particles_for_cell tests still pass
```

### Integration Tests: `tests/test_plugins/test_threshold_bg_subtraction.py`

```python
# Test cases for ThresholdBGSubtractionPlugin:
- validate() with no thresholds -> error message
- validate() with thresholds + channels -> empty errors
- run() creates derived FOV with correct metadata (condition, bio_rep, pixel_size_um)
- run() writes correct image (int32 intermediate, clip at zero, source dtype output)
- run() with uint16 image and bg_value > some pixels -> no underflow (CRITICAL)
- run() skips threshold with empty mask (warning)
- run() idempotent on re-run (same derived FOV reused)
- run() saves histogram PNG to exports/bgsub_histograms/
- run() caches channel image per FOV (does not reload for each threshold)
- info().name == "threshold_bg_subtraction"
```

## References

### Internal
- Plugin base class: `src/percell3/plugins/base.py:70`
- Split-halo derived FOV pattern: `src/percell3/plugins/builtin/split_halo_condensate_analysis.py:544`
- Existing bg_subtraction_core: `src/percell3/plugins/builtin/bg_subtraction_core.py:48`
- CLI plugin dispatch: `src/percell3/cli/menu.py:374`
- ExperimentStore.add_fov: `src/percell3/core/experiment_store.py:228`
- ExperimentStore.write_image: `src/percell3/core/experiment_store.py:384`

### Learnings Applied
- `docs/solutions/architecture-decisions/image-calculator-plugin-architecture.md` -- derived FOV naming, idempotent re-runs, custom CLI handler requirement, `is None` for optional params
- `docs/solutions/architecture-decisions/layer-based-architecture-redesign-learnings.md` -- fov_config traversal, Write-Invalidate-Cleanup pattern
- `docs/solutions/database-issues/zarr-sqlite-state-mismatch-re-thresholding.md` -- zarr/SQLite consistency, ExperimentStore as single mutation authority
- `docs/solutions/architecture-decisions/cli-module-code-review-findings.md` -- lazy imports in CLI, menu-as-thin-dispatcher pattern
- `docs/solutions/security-issues/core-module-p1-security-correctness-fixes.md` -- validate at system boundaries

### External Research
- scipy.signal.find_peaks: 15% relative prominence is appropriate for background estimation
- Histogram binning: 50 fixed bins acceptable for typical data; adaptive binning deferred
- Matplotlib memory: always `plt.close(fig)` in `finally` block; use Agg backend
