---
title: "Remove P3 code quality findings from napari viewer module (YAGNI, duplication, magic values)"
date: "2026-02-17"
category: "code-quality"
tags: ["yagni", "duplication", "test-quality", "magic-values", "napari-viewer", "code-review"]
severity: "p3"
module: "percell3.segment.viewer, percell3.cli"
problem_type: "code-simplification"
findings_addressed:
  - "P3-065: TestChangeDetection tested numpy builtins instead of PerCell code"
  - "P3-066: _NAME_TO_COLORMAP had 8 unused entries"
  - "P3-067: _default_contrast_limits() duplicated napari built-in functionality"
  - "P3-068: Redundant napari availability checks in 3 locations"
  - "P3-069: Magic 512x512 fallback value replaced with explicit error"
affected_files:
  - "src/percell3/segment/viewer/_viewer.py"
  - "src/percell3/cli/view.py"
  - "src/percell3/cli/menu.py"
  - "tests/test_segment/test_viewer.py"
resolution_type: "code-removal"
---

# Viewer Module P3 Refactoring and Cleanup

## Problem

The napari viewer module contained unnecessary complexity and redundant code patterns added during initial implementation. Five P3 (nice-to-have) findings from a multi-agent code review identified simplification opportunities where code was doing more than required:

1. **P3-065**: `TestChangeDetection` tests verified `np.array_equal()` behavior — testing numpy, not PerCell code
2. **P3-066**: `_NAME_TO_COLORMAP` had 12 entries but only 4 were used (dapi, gfp, rfp, brightfield)
3. **P3-067**: `_default_contrast_limits()` duplicated napari's built-in auto-computation of contrast limits
4. **P3-068**: napari availability checked redundantly in 3 locations (viewer/__init__.py, cli/view.py, cli/menu.py)
5. **P3-069**: Magic `(512, 512)` fallback shape when no image layers were loaded masked errors instead of surfacing them

## Root Cause

YAGNI (You Aren't Gonna Need It) anti-pattern violations during initial implementation:

- **Speculative mappings**: 12 colormap entries supporting aliases (hoechst, fitc, cy3, cy5, tritc, dic, phase, bf) that were never used in practice
- **Framework duplication**: napari computes optimal contrast from image dtype automatically; the custom function was redundant
- **Defensive over-checking**: same availability guard duplicated across 3 call sites when only one authoritative check was needed
- **Error masking**: hardcoded fallback dimensions for a situation that should be an explicit error

## Solution

### P3-066: Trim `_NAME_TO_COLORMAP`

Reduced from 12 to 4 entries — only channels actually used in tests and documentation:

```python
# Before (12 entries)
_NAME_TO_COLORMAP: dict[str, str] = {
    "dapi": "blue", "hoechst": "blue", "gfp": "green", "fitc": "green",
    "rfp": "red", "cy3": "red", "cy5": "magenta", "tritc": "red",
    "brightfield": "gray", "bf": "gray", "dic": "gray", "phase": "gray",
}

# After (4 entries)
_NAME_TO_COLORMAP: dict[str, str] = {
    "dapi": "blue", "gfp": "green", "rfp": "red", "brightfield": "gray",
}
```

Unknown channels still fall back to `"gray"` via the existing default return.

### P3-067: Remove `_default_contrast_limits()`

Deleted the entire function and its callsite. Simplified `_load_channel_layers` from a kwargs-dict pattern to a direct call:

```python
# Before
limits = _default_contrast_limits(data.dtype)
kwargs: dict[str, Any] = {"name": ch.name, "colormap": cmap, "blending": "additive"}
if limits is not None:
    kwargs["contrast_limits"] = limits
viewer.add_image(data, **kwargs)

# After
viewer.add_image(data, name=ch.name, colormap=cmap, blending="additive")
```

Also removed the unused `Any` import and the `TestContrastLimits` test class (3 tests that tested napari internals).

### P3-068: Consolidate napari availability checks

Removed pre-flight `NAPARI_AVAILABLE` checks from `cli/view.py` and `cli/menu.py`. The single authoritative check remains in `launch_viewer()` (viewer/__init__.py). CLI callers now catch `ImportError`:

```python
# cli/view.py — before
from percell3.segment.viewer import NAPARI_AVAILABLE, launch_viewer
if not NAPARI_AVAILABLE:
    console.print("[red]Error:[/red] napari is not installed...")
    raise SystemExit(1)
run_id = launch_viewer(store, region, condition, channel_list)

# cli/view.py — after
from percell3.segment.viewer import launch_viewer
try:
    run_id = launch_viewer(store, region, condition, channel_list)
except ImportError:
    console.print("[red]Error:[/red] napari is not installed.\n"
                  "Install with: [bold]pip install 'percell3[napari]'[/bold]")
    raise SystemExit(1)
```

Same pattern applied to `cli/menu.py`.

### P3-069: Remove magic 512x512 fallback

Replaced speculative shape detection with an explicit error:

```python
# Before — complex fallback with magic number
image_layers = [lyr for lyr in viewer.layers if hasattr(lyr, "data") and not isinstance(lyr, type)]
if image_layers:
    shape = image_layers[0].data.shape
    if hasattr(shape, '__len__') and len(shape) >= 2:
        label_shape = shape[-2:]
    else:
        label_shape = shape
else:
    label_shape = (512, 512)

# After — explicit error
if not viewer.layers:
    raise RuntimeError("Cannot create empty label layer: no image layers loaded.")
shape = viewer.layers[0].data.shape[-2:]
```

## Verification

- **Line delta**: -223 deleted, +38 added (net -185 lines)
- **Test suite**: 540 tests passing
- **Commit**: `b703675` on `feat/napari-viewer`
- **Removed tests**: 3 (`TestContrastLimits`) — tested napari internals, not PerCell code

## Prevention Strategies

- **YAGNI as a metric**: For lookup tables, only add entries proven by test data or user request. Start minimal and add reactively.
- **Check framework behavior first**: Before implementing a utility function, verify the framework doesn't already handle it. Document explicitly if overriding framework defaults.
- **Single-check pattern for optional dependencies**: Check availability once at module level, export as constant. Public wrapper raises `ImportError`. Private `_impl()` trusts the caller.
- **Explicit errors over magic fallbacks**: Replace hardcoded defaults that mask missing data with clear `RuntimeError` messages.
- **Test PerCell code, not libraries**: Before writing a test, ask "if this test passed, would a bug in PerCell code be caught?"

## Code Review Checklist (for future reviews)

- [ ] Lookup dicts are minimal — all keys present in test data or documented requirements
- [ ] No functions that merely wrap and re-export framework defaults
- [ ] Optional dependency availability checked exactly once per module
- [ ] No magic number fallbacks that mask real errors
- [ ] Tests exercise PerCell logic, not third-party library behavior
- [ ] No dead imports or unused type imports
- [ ] No redundant validation checks across multiple call sites

## Cross-References

- [Viewer Module Code Review Findings (P1/P2)](../architecture-decisions/viewer-module-code-review-findings.md) — comprehensive 14-finding review of the same module
- [CLI Module Code Review Findings](../architecture-decisions/cli-module-code-review-findings.md) — similar YAGNI and duplication findings in the CLI module
- [Cellpose 4.0 API Breaking Change](../integration-issues/cellpose-4-0-api-breaking-change.md) — related P3 YAGNI finding (segment_batch dead code)
