---
title: "feat: 3D Surface Plot Visualization Plugin"
type: feat
date: 2026-02-24
brainstorm: docs/brainstorms/2026-02-24-3d-surface-plot-plugin-brainstorm.md
---

# feat: 3D Surface Plot Visualization Plugin

## Overview

Add a 3D surface plot visualization plugin that renders a microscopy image as an interactive heightmap in napari. One channel defines the Z-axis elevation (terrain shape), a second channel drives a colormap painted onto that terrain (color overlay). Accessed from the Plugins menu, the user selects an FOV, draws an ROI in a 2D napari view, then generates and interacts with the 3D surface via a dock widget.

## Problem Statement / Motivation

Researchers need to visualize spatial correlations between two fluorescence channels. Flat 2D overlays show co-localization but obscure intensity relationships. A 3D heightmap where Channel A defines topology and Channel B defines color reveals where signal localizes relative to the intensity landscape — a view that 2D composites cannot provide.

## Proposed Solution

### Architecture

Introduce a **`VisualizationPlugin`** ABC alongside the existing `AnalysisPlugin`. The plugin system gains a second plugin type for read-only, viewer-launching plugins. The `PluginRegistry` discovers both types. The Plugins menu lists them together.

### Components

```
plugins/
├── base.py                          # + VisualizationPlugin ABC
├── registry.py                      # + viz plugin discovery
├── builtin/
│   ├── surface_plot_3d.py           # SurfacePlot3DPlugin (VisualizationPlugin)
│   └── _surface_mesh.py             # Pure-numpy mesh construction (no napari dep)
segment/viewer/
│   └── surface_plot_widget.py       # Qt dock widget (colormap, Z-scale, sigma, screenshot)
cli/
│   └── menu.py                      # + _run_surface_plot() handler
```

---

## Implementation Phases

### Phase 1: VisualizationPlugin ABC and Registry Support

**Files:** `src/percell3/plugins/base.py`, `src/percell3/plugins/registry.py`, `src/percell3/plugins/__init__.py`

#### 1.1 — Add `VisualizationPlugin` ABC to `base.py`

```python
# src/percell3/plugins/base.py

class VisualizationPlugin(ABC):
    """Base class for plugins that launch interactive viewers (no data writes)."""

    _INTERNAL_BASE_CLASS = True  # Prevents auto-registration of the ABC itself

    @abstractmethod
    def info(self) -> PluginInfo:
        """Return plugin metadata."""

    @abstractmethod
    def validate(self, store: ExperimentStore) -> list[str]:
        """Return list of error strings; empty = OK to launch."""

    @abstractmethod
    def launch(
        self,
        store: ExperimentStore,
        fov_id: int,
        parameters: dict[str, Any] | None = None,
    ) -> None:
        """Open the interactive visualization. Blocks until viewer is closed."""

    def get_parameter_schema(self) -> dict[str, Any]:
        """Optional JSON Schema for parameters."""
        return {}
```

Key difference from `AnalysisPlugin`: `launch()` returns `None` (no `PluginResult`), and there is no `store.start_analysis_run()` / `store.complete_analysis_run()` lifecycle.

#### 1.2 — Extend `PluginRegistry` in `registry.py`

Add a parallel `_viz_plugins: dict[str, type[VisualizationPlugin]]` alongside `_plugins`.

Update `discover()` to also find `VisualizationPlugin` subclasses from `percell3.plugins.builtin.*`:

```python
def discover(self) -> None:
    # Existing analysis plugin discovery...
    # Add: scan for VisualizationPlugin subclasses too
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if (issubclass(obj, VisualizationPlugin)
                and obj is not VisualizationPlugin
                and not getattr(obj, "_INTERNAL_BASE_CLASS", False)):
            instance = obj()
            self._viz_plugins[instance.info().name] = obj
```

Add methods:
- `list_viz_plugins() -> list[PluginInfo]`
- `get_viz_plugin(name: str) -> VisualizationPlugin`
- `list_all_plugins() -> list[tuple[str, PluginInfo]]` — returns `("analysis", info)` or `("visualization", info)` tuples for the menu

#### 1.3 — Export from `__init__.py`

Add `VisualizationPlugin` to the public exports.

#### Verification
- [x] `pytest tests/test_plugins/test_base.py -v` — ABC cannot be instantiated
- [x] `pytest tests/test_plugins/test_registry.py -v` — registry discovers both plugin types
- [x] Existing `AnalysisPlugin` tests still pass unchanged

---

### Phase 2: Pure-Numpy Mesh Construction

**File:** `src/percell3/plugins/builtin/_surface_mesh.py`

This module has **zero napari dependency** — pure numpy + scipy. Testable without a display server.

```python
# src/percell3/plugins/builtin/_surface_mesh.py

def build_surface(
    height: np.ndarray,        # (H, W) float — height channel ROI
    color: np.ndarray,         # (H, W) float — color channel ROI
    z_scale: float = 1.0,
    sigma: float = 0.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build napari Surface tuple from two 2D arrays.

    Returns:
        (vertices, faces, values) where:
        - vertices: (H*W, 3) float32, columns are (row, col, z)
        - faces: (2*(H-1)*(W-1), 3) int32, triangle indices
        - values: (H*W,) float32, color channel intensities
    """
```

#### Algorithm (fully vectorized, no loops)

1. **Normalize height** to [0, 1]: `(h - h.min()) / (h.max() - h.min() + eps)`
   - Avoids the "spike" problem where raw uint16 values (0–65535) dominate the XY extent
   - `z_scale` slider then multiplies normalized height (default ~50 to span roughly half the ROI width in Z)
2. **Smooth height** with `gaussian_filter(height, sigma)` if sigma > 0 (before mesh construction)
3. **Build vertices** via `np.meshgrid` + `np.stack` → `(H*W, 3)` float32
4. **Build faces** via vectorized index arithmetic:
   - For each 2x2 quad: two triangles `(tl, tr, bl)` and `(tr, br, bl)`
   - Consistent winding order for outward-facing normals
   - `vstack` → `(2*(H-1)*(W-1), 3)` int32
5. **Flatten color** via `color.ravel().astype(np.float32)` → vertex values

#### Performance

| ROI size | Vertices | Faces | Time (approx) | Memory |
|---|---|---|---|---|
| 256x256 | 65K | 130K | ~20 ms | ~2 MB |
| 512x512 | 262K | 524K | ~80 ms | ~8 MB |
| 1024x1024 | 1M | 2M | ~300 ms | ~30 MB |

ROIs larger than 512x512 will trigger a warning in the dock widget (not blocked, just warned).

#### Verification
- [x] `pytest tests/test_plugins/test_surface_mesh.py -v` — mesh shapes, dtypes, winding order
- [x] Test: height all-zeros → flat surface (no crash)
- [x] Test: height with NaN → replaced with 0 before meshing
- [x] Test: 1x1 ROI → raises ValueError (need at least 2x2)

---

### Phase 3: Dock Widget

**File:** `src/percell3/segment/viewer/surface_plot_widget.py`

Follows the pattern established by `CellposeWidget` — a class wrapping a `QWidget` with `.widget` attribute, connected to napari via `viewer.window.add_dock_widget()`.

#### Widget Layout

```
┌─────────────────────────────┐
│  3D Surface Plot            │
├─────────────────────────────┤
│  Height channel: [dropdown] │
│  Color channel:  [dropdown] │
├─────────────────────────────┤
│  Colormap: [viridis ▼]      │
│  Z-scale:  ═══●════  50    │
│  Smoothing: ══●═════  1.0  │
├─────────────────────────────┤
│  [ Generate Surface ]       │
├─────────────────────────────┤
│  [ Save Screenshot ]        │
└─────────────────────────────┘
```

#### Widget Class

```python
class SurfacePlotWidget:
    def __init__(self, viewer, store, fov_id, channel_names):
        self.widget = QWidget()
        # Channel dropdowns (QComboBox) populated from channel_names
        # Colormap dropdown: curated list (viridis, plasma, magma, inferno, turbo, hot, gray)
        # Z-scale slider: range 1–200, default 50, step 1
        # Smoothing sigma slider: range 0.0–10.0, default 1.0, step 0.5
        # "Generate Surface" button — triggers mesh build + surface layer add
        # "Save Screenshot" button — triggers viewer.screenshot()
```

#### Interaction Model

- **"Generate Surface" button** triggers the full pipeline: read ROI → `build_surface()` → `viewer.add_surface()` → switch to 3D mode
- **Colormap dropdown** change → `surface_layer.colormap = new_cmap` (instant, no re-mesh)
- **Z-scale slider** on release → rebuild vertices Z-column, `surface_layer.data = (new_verts, faces, values)` (debounced)
- **Smoothing sigma slider** on release → re-smooth height, rebuild mesh, `surface_layer.data = ...` (debounced)
- Slider changes use **on-release** events (not continuous drag) to avoid flooding the renderer

#### ROI Handling

When the viewer opens, a `Shapes` layer named `"ROI"` is added in rectangle mode:

```python
roi_layer = viewer.add_shapes(name="ROI", shape_type="rectangle",
                              edge_color="yellow", face_color="transparent")
roi_layer.mode = "add_rectangle"
```

When "Generate Surface" is clicked:
1. Check `roi_layer.data` is not empty — if empty, show status "Draw a rectangle ROI first"
2. If multiple shapes drawn, use the **last** one (most recent)
3. Extract bounding box: `row_min, col_min, row_max, col_max` from shape vertices
4. Clip to image bounds (0 to H, 0 to W)
5. Require at least 2x2 pixel ROI after clipping

#### 3D Mode Activation

After adding the Surface layer, set `viewer.dims.ndisplay = 3` to enable 3D rotation/zoom/pan. Set `shading="smooth"` on the surface layer for best visual quality.

#### Screenshot

```python
def _on_save_screenshot(self):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    fov_name = self._store.get_fov_by_id(self._fov_id).display_name
    path = self._store.experiment_path / "exports" / f"surface_plot_{fov_name}_{timestamp}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    self._viewer.screenshot(path=str(path), canvas_only=True, flash=True)
    console.print(f"Screenshot saved: {path}")
```

#### Verification
- [x] Widget instantiates without error (mock viewer + store)
- [ ] "Generate Surface" with no ROI shows warning, does not crash (manual test)
- [ ] Colormap change updates layer without re-meshing (manual test)
- [ ] Z-scale change rebuilds mesh geometry (manual test)
- [ ] Screenshot saves PNG to exports directory (manual test)

---

### Phase 4: Plugin Implementation

**File:** `src/percell3/plugins/builtin/surface_plot_3d.py`

```python
class SurfacePlot3DPlugin(VisualizationPlugin):

    def info(self) -> PluginInfo:
        return PluginInfo(
            name="surface_plot_3d",
            version="1.0.0",
            description="3D surface plot with dual-channel height + color overlay",
            author="PerCell3",
        )

    def validate(self, store: ExperimentStore) -> list[str]:
        errors = []
        channels = store.get_channels()
        if len(channels) < 2:
            errors.append("At least 2 channels required (height + color)")
        fovs = store.get_fovs()
        if not fovs:
            errors.append("No FOVs in experiment")
        return errors

    def launch(self, store, fov_id, parameters=None):
        # Imports napari here (not at module level) to keep plugin importable without napari
        import napari
        from percell3.segment.viewer.surface_plot_widget import SurfacePlotWidget

        channels = store.get_channels()
        channel_names = [ch.name for ch in channels]

        viewer = napari.Viewer(title=f"PerCell 3 — Surface Plot")

        # Load all channel images as 2D layers for ROI drawing context
        for ch in channels:
            data = store.read_image(fov_id, ch.name)
            viewer.add_image(data, name=ch.name, blending="additive")

        # Add ROI shapes layer
        roi_layer = viewer.add_shapes(
            name="ROI", shape_type="rectangle",
            edge_color="yellow", face_color="transparent",
        )
        roi_layer.mode = "add_rectangle"

        # Add dock widget
        widget = SurfacePlotWidget(viewer, store, fov_id, channel_names)
        viewer.window.add_dock_widget(widget.widget, name="3D Surface Plot", area="right")

        napari.run()
```

Key design choices:
- **Fresh `napari.Viewer()`** — does NOT reuse `launch_viewer()` or add CellposeWidget/EditWidget
- **napari import inside `launch()`** — keeps the plugin module importable without napari for registry discovery
- **All channels loaded as 2D layers** — provides visual context for ROI drawing
- **Blocks on `napari.run()`** — consistent with existing viewer pattern

#### Verification
- [x] Plugin discovered by registry with correct name and info
- [x] `validate()` catches <2 channels, no FOVs
- [ ] `launch()` opens napari with channel layers + ROI layer + dock widget (manual test)

---

### Phase 5: CLI Menu Wiring

**File:** `src/percell3/cli/menu.py`

#### 5.1 — Update `_plugins_menu()` to list viz plugins

After discovering analysis plugins, also list visualization plugins:

```python
def _plugins_menu(state: MenuState) -> None:
    registry = PluginRegistry()
    registry.discover()

    items = []
    # Existing analysis plugins...
    for i, info in enumerate(registry.list_plugins(), start=1):
        items.append(MenuItem(str(i), info.name, info.description,
                              _make_plugin_runner(registry, info.name)))

    # Visualization plugins
    for info in registry.list_viz_plugins():
        idx = len(items) + 1
        items.append(MenuItem(str(idx), info.name, info.description,
                              _make_viz_runner(registry, info.name)))
    # ... build Menu and run
```

#### 5.2 — Add `_run_surface_plot()` handler

```python
def _run_surface_plot(state: MenuState, registry: PluginRegistry) -> None:
    store = state.require_experiment()
    plugin = registry.get_viz_plugin("surface_plot_3d")

    # Validate before opening napari
    errors = plugin.validate(store)
    if errors:
        for e in errors:
            console.print(f"[red]Error:[/red] {e}")
        return

    # Select FOV
    fovs = store.get_fovs()
    seg_summary = store.get_fov_segmentation_summary()
    _show_fov_status_table(fovs, seg_summary)
    selected = _select_fovs_from_table(fovs)
    if not selected:
        return
    fov = selected[0]  # Single FOV

    console.print(f"\nOpening 3D Surface Plot for [bold]{fov.display_name}[/bold]...")
    console.print("Draw a rectangle ROI, select channels, then click 'Generate Surface'.\n")

    try:
        plugin.launch(store, fov.id)
    except ImportError:
        console.print("[red]Error:[/red] napari is not installed.\n"
                      "Install with: [bold]pip install 'percell3[napari]'[/bold]")
```

#### 5.3 — Wire into `_make_plugin_runner` (or new `_make_viz_runner`)

```python
def _make_viz_runner(registry, plugin_name: str):
    def handler(state: MenuState) -> None:
        if plugin_name == "surface_plot_3d":
            _run_surface_plot(state, registry)
        else:
            console.print(f"[yellow]No interactive handler for {plugin_name}[/yellow]")
    return handler
```

#### Verification
- [ ] "3D Surface Plot" appears in Plugins menu (manual test)
- [x] Validation errors shown before napari opens
- [x] FOV selection works with existing table/selection helpers
- [x] napari ImportError caught gracefully

---

### Phase 6: Tests

**Files:**
- `tests/test_plugins/test_surface_mesh.py` — mesh construction (no napari needed)
- `tests/test_plugins/test_surface_plot_3d.py` — plugin info, validate, registry discovery

#### Mesh Tests (pure numpy, fast)

```python
class TestBuildSurface:
    def test_basic_shape(self):
        """4x4 height → 16 vertices, 18 faces."""
    def test_dtype(self):
        """Vertices float32, faces int32, values float32."""
    def test_z_scale(self):
        """z_scale=2 doubles vertex Z values."""
    def test_sigma_smoothing(self):
        """sigma>0 produces smoother Z than sigma=0."""
    def test_nan_handling(self):
        """NaN in height replaced with 0."""
    def test_uniform_height(self):
        """All-same height → flat surface (no crash)."""
    def test_minimum_size(self):
        """1x1 input raises ValueError."""
    def test_color_values_match_shape(self):
        """values array length == number of vertices."""
```

#### Plugin Tests (no napari)

```python
class TestSurfacePlot3DPlugin:
    def test_info(self):
        """Plugin name is 'surface_plot_3d'."""
    def test_validate_needs_two_channels(self, experiment):
        """validate() returns error with <2 channels."""
    def test_validate_needs_fovs(self, experiment):
        """validate() returns error with 0 FOVs."""
    def test_validate_passes(self, experiment):
        """validate() returns [] with 2+ channels and FOVs."""
    def test_registry_discovers_viz_plugin(self):
        """PluginRegistry.discover() finds surface_plot_3d in viz plugins."""
```

#### Verification
- [x] `pytest tests/test_plugins/test_surface_mesh.py -v` — all mesh tests pass (16/16)
- [x] `pytest tests/test_plugins/test_surface_plot_3d.py -v` — all plugin tests pass (15/15)
- [x] `pytest tests/ -v` — full suite passes (938/938)

---

## Technical Considerations

### napari Surface Layer API

- **Vertex order:** `(row, col, z)` — row-major, matching numpy convention (NOT OpenGL `x, y, z`)
- **Face dtype:** Must be `int32` — float faces silently produce wrong geometry
- **Shading:** Use `shading="smooth"` for best visual quality on heightmaps
- **Updates:** Use `layer.vertex_values = ...` for colormap-only changes (cheap). Use `layer.data = (verts, faces, vals)` for geometry changes (expensive, debounce to ~200ms)
- **3D mode:** Must set `viewer.dims.ndisplay = 3` after adding the Surface layer
- **Performance:** Interactive performance degrades above ~1-2M triangles. Warn if ROI > 512x512

### Edge Cases Handled

| Scenario | Behavior |
|---|---|
| Experiment has <2 channels | `validate()` error before napari opens |
| No FOVs | `validate()` error before napari opens |
| No ROI drawn | "Draw a rectangle ROI first" status message |
| Multiple shapes drawn | Use the last (most recent) rectangle |
| ROI extends past image edge | Clip to image bounds |
| ROI < 2x2 pixels after clipping | Status message: "ROI too small" |
| Height channel all-zeros / uniform | Flat surface rendered (no crash), status note |
| NaN in height data | Replaced with 0 before meshing |
| napari not installed | `ImportError` caught, install instructions shown |
| Same channel for height and color | Allowed (valid, just redundant) |
| ROI > 512x512 | Warning shown, rendering proceeds |

### Institutional Learnings Applied

From `docs/solutions/`:
- **Specific exception handling** — no bare `except Exception:`. Catch `KeyError`, `ValueError`, `OSError` separately
- **Single-point napari check** — import napari inside `launch()`, not at module level
- **Fail loud** — ROI errors shown explicitly, no magic fallbacks (no 512x512 default)
- **Minimal colormap list** — curated subset of 7 colormaps, not every matplotlib colormap
- **Don't wrap framework defaults** — let napari handle contrast limits on image layers

---

## Acceptance Criteria

### Functional
- [x] `VisualizationPlugin` ABC exists alongside `AnalysisPlugin`
- [x] `PluginRegistry.discover()` finds both analysis and visualization plugins
- [ ] "3D Surface Plot" appears in the Plugins menu (manual test)
- [ ] User can select an FOV and draw an ROI in 2D napari view (manual test)
- [ ] "Generate Surface" creates a 3D heightmap from the height channel (manual test)
- [ ] Color channel intensity drives the surface colormap (manual test)
- [ ] Colormap dropdown switches the surface color interactively (manual test)
- [ ] Z-scale slider adjusts height exaggeration (rebuilds geometry on release) (manual test)
- [ ] Smoothing sigma slider adjusts Gaussian blur on height (rebuilds on release) (manual test)
- [ ] "Save Screenshot" exports PNG to `{experiment}/exports/` (manual test)
- [x] Validation prevents launch with <2 channels or 0 FOVs

### Quality
- [x] All existing tests pass unchanged
- [x] New mesh construction tests (pure numpy, no display needed)
- [x] New plugin tests (info, validate, registry discovery)
- [x] `pytest tests/ -v` — zero failures (938 passed)

## Verification

- [x] `pytest tests/test_plugins/test_surface_mesh.py -v` — mesh construction (16 passed)
- [x] `pytest tests/test_plugins/test_surface_plot_3d.py -v` — plugin + registry (15 passed)
- [x] `pytest tests/ -v` — full suite (938 passed)
- [ ] Manual: Plugins menu shows "3D Surface Plot" (user testing)
- [ ] Manual: Draw ROI → Generate Surface → 3D heightmap renders (user testing)
- [ ] Manual: Colormap, Z-scale, smoothing sliders work interactively (user testing)
- [ ] Manual: Screenshot saves to exports directory (user testing)

## References

- [napari Surface layer docs](https://napari.org/stable/howtos/layers/surface.html)
- [napari Surface API reference](https://napari.org/dev/api/napari.layers.Surface.html)
- Brainstorm: `docs/brainstorms/2026-02-24-3d-surface-plot-plugin-brainstorm.md`
- Existing plugin pattern: `src/percell3/plugins/builtin/local_bg_subtraction.py`
- Existing dock widget pattern: `src/percell3/segment/viewer/cellpose_widget.py`
- Existing CLI handler pattern: `_run_bg_subtraction()` in `src/percell3/cli/menu.py`
