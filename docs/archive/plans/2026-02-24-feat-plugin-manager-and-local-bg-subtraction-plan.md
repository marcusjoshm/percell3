---
title: "feat: Plugin Manager and Local Background Subtraction"
type: feat
date: 2026-02-24
brainstorm: docs/brainstorms/2026-02-24-local-background-subtraction-plugin-brainstorm.md
---

# Plugin Manager and Local Background Subtraction Plugin

## Overview

Build the PerCell 3 plugin system (registry, discovery, base class, menu integration) and implement the first real plugin: **Local Background Subtraction**. The plugin ports the m7G Cap Enrichment Analysis algorithm from PerCell 1 into a universal, channel-agnostic tool that works with any experiment.

**Two components, built in sequence:**
1. **Plugin Manager** — `AnalysisPlugin` ABC, `PluginRegistry`, menu integration
2. **Local Background Subtraction Plugin** — per-particle local background estimation and subtraction using Gaussian peak detection

## Problem Statement

PerCell 3 has a fully designed but unimplemented plugin system (`src/percell3/plugins/` contains only docstrings). The existing spec at `docs/05-plugins/spec.md` defines the ABC and registry interfaces. Meanwhile, the original PerCell's m7G Cap Enrichment Analysis uses ImageJ macros and hardcoded channel assignments — it needs to be ported to pure Python with flexible channel selection.

## Technical Design

### Key Design Decisions

| Decision | Resolution | Rationale |
|----------|-----------|-----------|
| Plugin ABC method | `run(store, cell_ids, parameters, progress_callback)` | Matches existing spec at `docs/05-plugins/spec.md` |
| Plugin discovery | Hybrid: directory scan for built-ins, entry-points deferred | YAGNI — entry-points added when third-party plugins exist |
| BG-sub metric storage | Cell-level aggregates in `measurements` table using unique metric names | No schema migration needed — `bg_sub_mean_intensity` is a different metric from `mean_intensity` |
| BG-sub scope | `whole_cell` (existing scope) | Metric names are distinct enough; no new scope value needed |
| Per-particle detail | CSV export only | `measurements` table is cell-level; per-particle granularity goes to CSV |
| Background estimation | Gaussian smoothing + peak detection (port from original) | Proven algorithm, robust to bright contaminants |
| Ring overlap handling | Subtract ALL same-cell particle masks from ring | Prevents neighboring particles from contaminating background |
| Zero-ring-pixel fallback | Skip particle, record NaN, add warning | Graceful degradation |
| Re-run behavior | `INSERT OR REPLACE` (overwrites), with user confirmation | Matches existing measurement pattern |

### Metric Names Written by Plugin

Cell-level measurements (stored in `measurements` table, scope=`whole_cell`):
- `bg_sub_mean_intensity` — mean of per-pixel bg-subtracted values across all particles in the cell
- `bg_sub_integrated_intensity` — sum of per-pixel bg-subtracted values across all particles
- `bg_estimate` — weighted mean background estimate across all particles in the cell
- `bg_sub_particle_count` — number of particles with valid background estimates

Per-particle columns (CSV export only):
- `particle_id`, `cell_id`, `fov_name`, `condition`, `bio_rep`
- `area_pixels`, `raw_mean_intensity`, `raw_integrated_intensity`
- `bg_estimate`, `bg_ring_pixels`, `bg_sub_mean_intensity`, `bg_sub_integrated_intensity`

### No Schema Migration Required

The `measurements` table UNIQUE constraint is `(cell_id, channel_id, metric, scope)`. Since `bg_sub_mean_intensity` is a distinct metric name from `mean_intensity`, both can coexist with scope=`whole_cell` on the same cell and channel. The existing `INSERT OR REPLACE` semantics handle re-runs.

## Implementation Phases

### Phase 1: Plugin Infrastructure

Build the core plugin system that all future plugins depend on.

**Files to create:**

#### `src/percell3/plugins/base.py`

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

@dataclass(frozen=True)
class PluginInfo:
    name: str
    version: str
    description: str
    author: str = ""
    required_channels: list[str] | None = None

@dataclass(frozen=True)
class PluginResult:
    measurements_written: int
    cells_processed: int
    custom_outputs: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

class AnalysisPlugin(ABC):
    @abstractmethod
    def info(self) -> PluginInfo: ...

    @abstractmethod
    def validate(self, store) -> list[str]: ...

    @abstractmethod
    def run(self, store, cell_ids=None, parameters=None,
            progress_callback=None) -> PluginResult: ...

    def get_parameter_schema(self) -> dict:
        return {}
```

#### `src/percell3/plugins/registry.py`

```python
class PluginRegistry:
    def __init__(self):
        self._plugins: dict[str, type[AnalysisPlugin]] = {}

    def discover(self) -> None:
        """Scan percell3/plugins/builtin/ for AnalysisPlugin subclasses."""

    def list_plugins(self) -> list[PluginInfo]: ...

    def get_plugin(self, name: str) -> AnalysisPlugin: ...

    def run_plugin(self, name, store, cell_ids=None,
                   parameters=None, progress_callback=None) -> PluginResult:
        """Full lifecycle: validate -> start_analysis_run -> run -> complete."""
```

Discovery scans `src/percell3/plugins/builtin/` for Python files, imports each, and registers any `AnalysisPlugin` subclass found. Uses `importlib` — no filesystem path hacks.

#### `src/percell3/plugins/__init__.py`

Update with public exports:
```python
from percell3.plugins.base import AnalysisPlugin, PluginInfo, PluginResult
from percell3.plugins.registry import PluginRegistry

__all__ = ["AnalysisPlugin", "PluginInfo", "PluginResult", "PluginRegistry"]
```

**Checklist:**
- [x] Create `src/percell3/plugins/base.py` with `PluginInfo`, `PluginResult`, `AnalysisPlugin` ABC
- [x] Create `src/percell3/plugins/registry.py` with `PluginRegistry` class
- [x] Update `src/percell3/plugins/__init__.py` with public exports
- [x] Create `tests/test_plugins/test_base.py` — test ABC contract enforcement
- [x] Create `tests/test_plugins/test_registry.py` — test discovery, lifecycle, error handling

### Phase 2: Plugin Menu Integration

Wire the plugin manager into the interactive CLI menu.

**Files to modify:**

#### `src/percell3/cli/menu.py`

- Enable menu item 8 ("Plugins") by setting `enabled=True` and providing a handler
- Create `_plugins_menu(state)` handler that:
  1. Discovers plugins via `PluginRegistry`
  2. Shows a numbered list of available plugins with descriptions
  3. User selects a plugin → delegates to plugin-specific configuration handler
  4. Runs the plugin with progress bar
  5. Shows result summary + "Press Enter to continue"

```python
def _plugins_menu(state: MenuState) -> None:
    store = state.require_experiment()
    registry = PluginRegistry()
    registry.discover()
    plugins = registry.list_plugins()
    if not plugins:
        console.print("\n[yellow]No plugins available.[/yellow]")
        return
    # Show numbered list, user selects, run plugin with config
```

- Each plugin's `get_parameter_schema()` drives the interactive prompts
- For the Local BG Sub plugin: custom handler function that walks through channel/mask selection

**Checklist:**
- [x] Change menu item 8 in `menu.py` to `enabled=True` with `_plugins_menu` handler
- [x] Implement `_plugins_menu(state)` — discovery, list, selection
- [x] Implement `_run_plugin(state, registry, plugin_name)` — generic plugin runner with progress
- [x] Update `tests/test_cli/test_menu.py` — test plugin menu item is selectable

### Phase 3: Background Subtraction Algorithm

The core computational module — pure numpy/scipy, no CLI or store dependencies.

**File to create:**

#### `src/percell3/plugins/builtin/bg_subtraction_core.py`

```python
@dataclass(frozen=True)
class ParticleBGResult:
    particle_label: int
    cell_id: int
    area_pixels: int
    raw_mean_intensity: float
    raw_integrated_intensity: float
    bg_estimate: float
    bg_ring_pixels: int
    bg_sub_mean_intensity: float
    bg_sub_integrated_intensity: float
    peak_info: dict | None = None  # For histogram export

def estimate_background_gaussian(
    ring_intensities: np.ndarray,
    n_bins: int = 50,
    sigma: float = 2.0,
    max_background: float | None = None,
) -> tuple[float, dict]:
    """Estimate background from ring pixel histogram using Gaussian peak detection.

    Port of PerCell 1 _find_gaussian_peaks algorithm.

    Returns:
        (background_value, peak_info_dict)
    """

def compute_background_ring(
    particle_mask: np.ndarray,
    all_particles_mask: np.ndarray,
    exclusion_mask: np.ndarray | None,
    dilation_pixels: int,
    image_shape: tuple[int, int],
) -> np.ndarray:
    """Create background ring by dilating particle, subtracting exclusions.

    Steps:
    1. Dilate particle_mask by dilation_pixels (disk structuring element)
    2. Ring = dilated AND NOT all_particles_mask
    3. If exclusion_mask: ring = ring AND NOT exclusion_mask
    4. Clip to image bounds (implicit via array shapes)

    Returns:
        Boolean ring mask.
    """

def process_particles_for_cell(
    cell_id: int,
    cell_mask: np.ndarray,
    particle_labels: np.ndarray,
    measurement_image: np.ndarray,
    exclusion_mask: np.ndarray | None,
    dilation_pixels: int,
) -> list[ParticleBGResult]:
    """Process all particles in a cell, returning per-particle BG results."""
```

**Algorithm detail — `estimate_background_gaussian` (ported from `_intensity_analysis_base.py:298`):**
1. Build histogram of ring pixel intensities (`np.histogram`, `n_bins=50`, range `[0, max]`)
2. Smooth with `scipy.ndimage.gaussian_filter1d(sigma=2)`
3. Find peaks with `scipy.signal.find_peaks(prominence=0.15 * max_smooth)`
4. If no peaks: use argmax of smoothed histogram as background
5. If `max_background` set: prefer most prominent peak below threshold
6. Otherwise: use lowest-position peak as background (leftmost = dimmest = background)
7. Return `(background_value, peak_info_dict)`

**Algorithm detail — `compute_background_ring`:**
1. `from scipy.ndimage import binary_dilation`
2. `from skimage.morphology import disk`
3. `dilated = binary_dilation(particle_mask, structure=disk(dilation_pixels))`
4. `ring = dilated & ~all_particles_mask` (exclude ALL particles in this cell, not just current)
5. If exclusion mask: `ring = ring & ~exclusion_mask`
6. Return ring boolean mask

**Checklist:**
- [x] Create `src/percell3/plugins/builtin/bg_subtraction_core.py`
- [x] Implement `estimate_background_gaussian()` — port from original
- [x] Implement `compute_background_ring()` — dilation + exclusion
- [x] Implement `process_particles_for_cell()` — orchestrates per-cell processing
- [x] Create `tests/test_plugins/test_bg_subtraction_core.py`:
  - [x] Test Gaussian peak detection on known histogram (single peak, multi-peak)
  - [x] Test peak detection with empty array → returns None
  - [x] Test peak detection with max_background constraint
  - [x] Test ring computation with no exclusion
  - [x] Test ring computation with exclusion mask
  - [x] Test ring at image edge (clips correctly)
  - [x] Test overlapping particles (ring excludes neighbors)
  - [x] Test zero ring pixels → handled gracefully
  - [x] Test full per-cell processing with synthetic data

### Phase 4: Local Background Subtraction Plugin

Wire the core algorithm into the `AnalysisPlugin` ABC.

**File to create:**

#### `src/percell3/plugins/builtin/local_bg_subtraction.py`

```python
class LocalBGSubtractionPlugin(AnalysisPlugin):
    """Per-particle local background subtraction using Gaussian peak detection."""

    def info(self) -> PluginInfo:
        return PluginInfo(
            name="local_bg_subtraction",
            version="1.0.0",
            description="Per-particle local background subtraction with Gaussian peak detection",
            author="PerCell Team",
        )

    def validate(self, store) -> list[str]:
        """Check experiment has cells, channels, and particle masks."""
        errors = []
        # Must have cells
        # Must have at least one channel
        # Must have at least one threshold run with particles
        return errors

    def run(self, store, cell_ids=None, parameters=None,
            progress_callback=None) -> PluginResult:
        """Execute background subtraction.

        Parameters dict:
            measurement_channel: str — channel for intensity measurement
            particle_channel: str — channel whose particle mask to use
            exclusion_channel: str | None — optional exclusion mask channel
            dilation_pixels: int — ring dilation amount (default: 5)
            export_histograms: bool — save histogram PNGs (default: False)
            output_dir: str | None — directory for CSV/histogram export
        """
```

**`run()` flow:**
1. Extract parameters from dict
2. Look up `threshold_run_id` for `particle_channel` (most recent)
3. If no threshold run → raise with "Run thresholding first" message
4. Get FOV list (from `cell_ids` or all FOVs with cells)
5. If `exclusion_channel`: load its threshold mask per-FOV
6. `start_analysis_run("local_bg_subtraction", params_json)`
7. For each FOV:
   a. Read cell labels, particle labels, measurement channel image
   b. Read threshold mask for particle channel
   c. Optionally read exclusion mask
   d. For each cell: call `process_particles_for_cell()`
   e. Aggregate per-cell: compute `bg_sub_mean_intensity`, `bg_sub_integrated_intensity`, `bg_estimate`, `bg_sub_particle_count`
   f. Build `MeasurementRecord` list with `channel_id` = measurement channel, `scope` = `whole_cell`
   g. `store.add_measurements(records)`
   h. Collect per-particle results for CSV
   i. Call `progress_callback(current_fov, total_fovs, fov_name)`
8. Export per-particle CSV to `{experiment}/exports/bg_subtraction_{meas_channel}_{timestamp}.csv`
9. If `export_histograms`: save histogram PNGs to `{experiment}/exports/histograms/`
10. `complete_analysis_run(run_id, "completed", cells_processed)`
11. Return `PluginResult`

**Checklist:**
- [x] Create `src/percell3/plugins/builtin/local_bg_subtraction.py`
- [x] Implement `info()`, `validate()`, `get_parameter_schema()`
- [x] Implement `run()` with full lifecycle
- [x] Implement per-particle CSV export
- [ ] Implement optional histogram PNG export (deferred — not MVP)
- [x] Create `tests/test_plugins/test_local_bg_subtraction.py`:
  - [x] Test validate() with no experiment → errors
  - [x] Test validate() with no particles → errors
  - [x] Test validate() with valid experiment → empty errors
  - [x] Test run() with synthetic data (known background, known particles)
  - [x] Test run() writes correct metric names to measurements table
  - [x] Test run() exports CSV with expected columns
  - [x] Test run() with exclusion mask
  - [x] Test run() with zero particles in a cell → skip gracefully
  - [x] Test re-run overwrites previous results

### Phase 5: Plugin CLI Handler

Create the interactive menu handler for the Local BG Subtraction plugin. This is plugin-specific UI that walks users through channel/mask selection.

**File to modify:**

#### `src/percell3/cli/menu.py`

Add `_run_bg_subtraction(state, registry)` handler:

```python
def _run_bg_subtraction(state: MenuState, registry: PluginRegistry) -> None:
    store = state.require_experiment()

    # Step 1: Select measurement channel
    channels = store.get_channels()
    console.print("\n[bold]Step 1: Measurement Channel[/bold]")
    console.print("  Select the channel to measure intensities from.\n")
    meas_ch = numbered_select_one([c.name for c in channels], "Measurement channel")

    # Step 2: Select particle mask channel
    # Filter to channels that have threshold runs with particles
    particle_channels = _get_channels_with_particles(store)
    if not particle_channels:
        console.print("\n[red]No particle masks found.[/red]")
        console.print("[dim]Run 'Apply threshold' first to generate particle masks.[/dim]")
        return
    console.print("\n[bold]Step 2: Particle Mask[/bold]")
    console.print("  Select the thresholded particle mask to use.\n")
    particle_ch = numbered_select_one(particle_channels, "Particle mask")

    # Step 3: Optional exclusion mask
    console.print("\n[bold]Step 3: Exclusion Mask (optional)[/bold]")
    console.print("  Optionally exclude another mask's particles from measurement.\n")
    other_particle_channels = [c for c in particle_channels if c != particle_ch]
    excl_ch = None
    if other_particle_channels:
        choices = ["(none)"] + other_particle_channels
        choice = numbered_select_one(choices, "Exclusion mask")
        if choice != "(none)":
            excl_ch = choice

    # Step 4: Dilation amount
    console.print("\n[bold]Step 4: Dilation[/bold]")
    dilation = menu_prompt("Dilation pixels (default=5)", default="5")
    dilation = int(dilation)

    # Step 5: FOV selection (reuse existing pattern)
    fov_list = _select_fovs(store)

    # Step 6: Confirmation
    # Show settings summary table, ask Proceed?

    # Step 7: Run with progress bar
    parameters = {
        "measurement_channel": meas_ch,
        "particle_channel": particle_ch,
        "exclusion_channel": excl_ch,
        "dilation_pixels": dilation,
    }
    with make_progress() as progress:
        task = progress.add_task("Background subtraction...", total=len(fov_list))
        def on_progress(current, total, fov_name):
            progress.update(task, total=total, completed=current,
                          description=f"Processing {fov_name}")
        result = registry.run_plugin(
            "local_bg_subtraction", store,
            cell_ids=cell_ids, parameters=parameters,
            progress_callback=on_progress,
        )

    # Step 8: Summary
    console.print(f"\n[green]Background subtraction complete[/green]")
    console.print(f"  Cells processed: {result.cells_processed}")
    console.print(f"  Measurements written: {result.measurements_written}")
    if result.warnings:
        for w in result.warnings:
            console.print(f"  [yellow]Warning: {w}[/yellow]")
```

**Checklist:**
- [x] Implement `_run_bg_subtraction(state, registry)` interactive handler
- [x] Implement channel-with-particles lookup via threshold_runs
- [x] Wire into `_plugins_menu` as the handler for "local_bg_subtraction"
- [x] Add confirmation step with settings summary
- [x] Update `tests/test_cli/test_menu.py` — test plugin menu requires experiment

### Phase 6: Integration Tests

End-to-end tests using a real (synthetic) experiment.

**File to create:**

#### `tests/test_plugins/test_bg_subtraction_integration.py`

```python
class TestBGSubtractionIntegration:
    """Full pipeline: create experiment -> import -> segment -> threshold -> bg-sub."""

    def test_full_pipeline_with_synthetic_data(self, tmp_path):
        """Synthetic experiment with known background should produce correct BG-sub values."""
        # Create experiment with 2 channels (DAPI for mask, GFP for measurement)
        # Import synthetic image: bright particles on dim background
        # Segment cells (mock segmentation)
        # Threshold GFP channel to find particles
        # Run LocalBGSubtractionPlugin
        # Verify bg_sub_mean_intensity ≈ expected value
        # Verify CSV export exists with correct columns

    def test_with_exclusion_mask(self, tmp_path):
        """Exclusion mask should reduce background ring contamination."""

    def test_no_particles_graceful(self, tmp_path):
        """FOV with no particles should be skipped with warning."""

    def test_plugin_results_in_standard_export(self, tmp_path):
        """BG-sub metrics should appear in standard CSV export."""
```

**Checklist:**
- [x] Create integration test with synthetic experiment
- [x] Test full pipeline end-to-end
- [x] Test exclusion mask flow
- [x] Test graceful handling of missing particles
- [x] Verify CSV export includes bg-sub metrics

## File Summary

| File | Action | Phase |
|------|--------|-------|
| `src/percell3/plugins/__init__.py` | Modify | 1 |
| `src/percell3/plugins/base.py` | Create | 1 |
| `src/percell3/plugins/registry.py` | Create | 1 |
| `src/percell3/plugins/builtin/__init__.py` | Modify (add imports) | 1 |
| `src/percell3/plugins/builtin/bg_subtraction_core.py` | Create | 3 |
| `src/percell3/plugins/builtin/local_bg_subtraction.py` | Create | 4 |
| `src/percell3/cli/menu.py` | Modify (enable plugins, add handlers) | 2, 5 |
| `tests/test_plugins/__init__.py` | Create | 1 |
| `tests/test_plugins/test_base.py` | Create | 1 |
| `tests/test_plugins/test_registry.py` | Create | 1 |
| `tests/test_plugins/test_bg_subtraction_core.py` | Create | 3 |
| `tests/test_plugins/test_local_bg_subtraction.py` | Create | 4 |
| `tests/test_plugins/test_bg_subtraction_integration.py` | Create | 6 |

## Acceptance Criteria

### Functional Requirements

- [ ] `AnalysisPlugin` ABC can be subclassed; `run()` enforced
- [ ] `PluginRegistry.discover()` finds built-in plugins in `plugins/builtin/`
- [ ] `PluginRegistry.run_plugin()` calls `validate()` → `start_analysis_run()` → `run()` → `complete_analysis_run()`
- [ ] Menu item "Plugins" is enabled and lists discovered plugins
- [ ] Local BG Sub plugin validates: requires cells, particle masks, channels
- [ ] Local BG Sub plugin errors clearly if no particle masks exist ("Run thresholding first")
- [ ] User can select measurement channel, particle mask channel, exclusion mask, dilation amount
- [ ] Background ring correctly excludes all same-cell particles + exclusion mask pixels
- [ ] Gaussian peak detection produces correct background estimates on synthetic data
- [ ] Per-cell `bg_sub_mean_intensity`, `bg_sub_integrated_intensity`, `bg_estimate` written to measurements table
- [ ] Per-particle CSV exported to experiment's exports directory
- [ ] Optional histogram PNGs saved when flag is enabled
- [ ] Re-running overwrites previous results (with user confirmation in menu)
- [ ] Results appear in standard `percell3 export` CSV output

### Non-Functional Requirements

- [ ] No new eager imports at module level (lazy-load all plugin code)
- [ ] `percell3 --help` still completes in < 500ms
- [ ] Plugin processing handles edge cases: particles at image boundaries, zero ring pixels, cells with no particles

### Quality Gates

- [ ] `pytest tests/test_plugins/ -v` — all tests pass
- [ ] `pytest tests/ -v` — full suite passes (no regressions)
- [ ] No direct access to `store._conn` or imports of `core.queries`/`core.schema` from plugin code

## Dependencies & Prerequisites

- **Existing:** numpy, scipy, scikit-image (already in project dependencies)
- **No new dependencies required**
- **Prerequisite data:** Experiment must have cells (segmentation) and particle masks (thresholding) before plugin can run

## References

### Internal References

- Plugin spec: `docs/05-plugins/spec.md`
- Plugin module CLAUDE.md: `docs/05-plugins/CLAUDE.md`
- Original algorithm: `/Users/leelab/percell/percell/plugins/_intensity_analysis_base.py:298` (`_find_gaussian_peaks`)
- Original ROI analysis: `/Users/leelab/percell/percell/plugins/_intensity_analysis_base.py:368` (`_analyze_roi_intensity_from_rois`)
- ExperimentStore API: `src/percell3/core/experiment_store.py`
- Schema: `src/percell3/core/schema.py`
- ParticleAnalyzer pattern: `src/percell3/measure/particle_analyzer.py`
- Measurement models: `src/percell3/core/models.py`
- Menu system: `src/percell3/cli/menu.py`, `src/percell3/cli/menu_system.py`
- Brainstorm: `docs/brainstorms/2026-02-24-local-background-subtraction-plugin-brainstorm.md`

### Institutional Learnings

- **ExperimentStore boundary enforcement** (`docs/solutions/architecture-decisions/segment-module-private-api-encapsulation-fix.md`): Plugins MUST only use public `ExperimentStore` API. Never access `store._conn` or import `queries`/`schema`.
- **Lazy import pattern** (`docs/solutions/architecture-decisions/cli-module-code-review-findings.md`): Plugin code must be lazily imported to maintain CLI startup performance.
- **Input name validation** (`docs/solutions/security-issues/core-module-p1-security-correctness-fixes.md`): Any user-supplied names in file paths must go through `_validate_name()`.
- **Table-first UX** (`docs/solutions/design-gaps/import-flow-table-first-ui-and-heuristics.md`): Show numbered tables for selection, never flat prompts.
