---
status: pending
priority: p2
issue_id: "060"
tags: [code-review, napari-viewer, linux, wayland]
dependencies: []
---

# Display Check Misses Wayland — Viewer Fails on Wayland Systems

## Problem Statement
In `src/percell3/segment/viewer/_viewer.py:81`, the display availability check only looks for `DISPLAY` environment variable (X11). Modern Linux systems using Wayland set `WAYLAND_DISPLAY` instead. Users on Wayland-only systems (Ubuntu 22.04+, Fedora) get a "No display available" error even when they have a working graphical environment.

## Findings
- **File:** `src/percell3/segment/viewer/_viewer.py:81`
- Flagged by: kieran-python-reviewer (C3)
- Only `os.environ.get("DISPLAY")` is checked
- Wayland is increasingly default on modern Linux distributions

## Proposed Solutions
### Option 1 (Recommended): Check both DISPLAY and WAYLAND_DISPLAY
```python
if sys.platform != "darwin" and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
```

## Acceptance Criteria
- [ ] Both `DISPLAY` and `WAYLAND_DISPLAY` checked
- [ ] Test covers Wayland-only scenario
- [ ] Works on X11, Wayland, and macOS
