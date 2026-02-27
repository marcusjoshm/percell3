---
title: "feat: Napari background subtraction widget"
type: feat
date: 2026-02-27
branch: feat/split-halo-condensate-analysis
---

# feat: Napari background subtraction widget

A napari dock widget that subtracts a user-specified background value from selected channels, creating a new derived FOV (`bg_sub_{fov_name}`) with the result. Original image is preserved.

## Acceptance Criteria

- [x] Dock widget appears in napari viewer with: numeric input (QDoubleSpinBox), channel checkboxes, "Apply" button, status label
- [x] Subtracts user value from each pixel of selected channels, clips to 0
- [x] Creates derived FOV named `bg_sub_{fov_display_name}` with subtracted images
- [x] Overwrites existing `bg_sub_*` derived FOV on re-run (idempotent)
- [x] Unselected channels are copied unchanged to derived FOV
- [x] Status label shows result (e.g., "Created bg_sub_FOV_001 — 3 channels")
- [x] Preserves original dtype (uint8, uint16, etc.)
- [x] Tests for core subtraction logic and derived FOV creation

## Implementation

### Phase 1: Widget + core logic

- [x] Create `src/percell3/segment/viewer/bg_subtraction_widget.py`

Follow `EdgeRemovalWidget` pattern exactly:

```python
# src/percell3/segment/viewer/bg_subtraction_widget.py

class BGSubtractionWidget:
    def __init__(self, viewer, store, fov_id, channel_names):
        from qtpy.QtWidgets import (
            QCheckBox, QDoubleSpinBox, QLabel,
            QPushButton, QVBoxLayout, QWidget,
        )
        self._viewer = viewer
        self._store = store
        self._fov_id = fov_id

        self.widget = QWidget()
        layout = QVBoxLayout()

        # BG value input (QDoubleSpinBox, range 0-65535, step 1.0)
        self._bg_spin = QDoubleSpinBox()

        # Channel checkboxes (one per channel from channel_names)
        self._channel_checks: dict[str, QCheckBox] = {}

        # Apply button
        self._apply_btn = QPushButton("Apply Background Subtraction")
        self._apply_btn.clicked.connect(self._on_apply)

        # Status label
        self._status = QLabel("")

        self.widget.setLayout(layout)

    def _on_apply(self):
        bg_value = self._bg_spin.value()
        selected = [name for name, cb in self._channel_checks.items() if cb.isChecked()]
        # Create/overwrite derived FOV, subtract, clip to 0
```

Core subtraction logic (inside `_on_apply`):
1. Get `fov_info = store.get_fov_by_id(fov_id)`
2. Build `existing_fov_map = {f.display_name: f.id for f in store.get_fovs()}`
3. `derived_name = f"bg_sub_{fov_info.display_name}"`
4. If exists in map → reuse ID; else → `store.add_fov(...)` with same condition/bio_rep/dimensions
5. For each channel:
   - If selected: `data = store.read_image_numpy(fov_id, ch) - bg_value`, clip to 0, preserve dtype
   - If not selected: copy unchanged `data = store.read_image_numpy(fov_id, ch)`
   - `store.write_image(derived_fov_id, ch, result)`
6. Update status label

### Phase 2: Register in viewer

- [x] Modify `src/percell3/segment/viewer/_viewer.py` — add to `_launch()`

```python
bg_sub_w = BGSubtractionWidget(viewer, store, fov_id, channel_names)
viewer.window.add_dock_widget(bg_sub_w.widget, name="BG Subtraction", area="right")
```

### Phase 3: Tests

- [x] Create `tests/test_segment/test_bg_subtraction_widget.py`
  - [x] Test subtraction clips to zero (no negative values)
  - [x] Test dtype preservation (uint16 in → uint16 out)
  - [x] Test derived FOV created with correct name
  - [x] Test re-run overwrites existing derived FOV
  - [x] Test unselected channels copied unchanged

## Key Patterns to Follow

| Pattern | Reference |
|---------|-----------|
| Widget class structure | `src/percell3/segment/viewer/edge_removal_widget.py` |
| QDoubleSpinBox usage | `src/percell3/segment/viewer/cellpose_widget.py:150` |
| Derived FOV creation + overwrite | `src/percell3/plugins/builtin/split_halo_condensate_analysis.py:425` |
| Dock widget registration | `src/percell3/segment/viewer/_viewer.py:138` |
| Image read/write | `store.read_image_numpy()` / `store.write_image()` |

## Gotchas (from learnings)

- **Lazy-import Qt widgets** inside `__init__`, not at module level (viewer is optional)
- **Use specific exception types**, never bare `except:` (silent data loss risk)
- **Derived FOV needs all FovInfo fields**: condition, bio_rep, width, height, pixel_size_um
- **Subtraction math**: cast to float64 before subtracting, then clip, then cast back to original dtype

## References

- **Brainstorm:** `docs/brainstorms/2026-02-27-napari-background-subtraction-widget-brainstorm.md`
- **Widget pattern:** `src/percell3/segment/viewer/edge_removal_widget.py`
- **Derived FOV pattern:** `src/percell3/plugins/builtin/split_halo_condensate_analysis.py:425-467`
- **Learnings:** `docs/solutions/code-quality/viewer-module-p3-refactoring-and-cleanup.md`
- **Learnings:** `docs/solutions/architecture-decisions/viewer-module-code-review-findings.md`
