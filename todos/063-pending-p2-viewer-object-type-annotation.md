---
status: pending
priority: p2
issue_id: "063"
tags: [code-review, napari-viewer, type-safety]
dependencies: []
---

# `viewer: object` Type Annotation Loses Type Checking

## Problem Statement
In `src/percell3/segment/viewer/_viewer.py`, the napari `Viewer` instance is typed as `object` to avoid importing napari at type-check time. This means all method calls on the viewer (`viewer.add_image`, `viewer.add_labels`, etc.) are unchecked — typos and wrong arguments won't be caught by mypy.

## Findings
- **File:** `src/percell3/segment/viewer/_viewer.py` — `_launch()` function signature
- Flagged by: kieran-python-reviewer (I2)
- `viewer: object` means no autocomplete, no type checking on viewer API calls
- napari is an optional dependency so can't be in regular imports

## Proposed Solutions
### Option 1 (Recommended): Use TYPE_CHECKING guard
```python
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    import napari
```
Then type as `viewer: napari.Viewer`.

### Option 2: Keep as-is, add # type: ignore comments
Lower effort but no type safety.

## Acceptance Criteria
- [ ] Viewer typed as `napari.Viewer` under TYPE_CHECKING
- [ ] mypy passes with napari installed
- [ ] No runtime import of napari at module level
