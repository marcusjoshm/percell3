---
status: complete
priority: p1
issue_id: "035"
tags: [code-review, segment, security]
dependencies: []
---

# Arbitrary Code Execution Risk via `np.load(allow_pickle=True)` in ROI Import

## Problem Statement

`RoiImporter.import_cellpose_seg()` uses `np.load(str(seg_path), allow_pickle=True)` which deserializes arbitrary Python objects. A crafted `_seg.npy` file can execute arbitrary code during load, before any validation runs.

This is inherent to the Cellpose `_seg.npy` format (it stores a dictionary, requiring pickle). The risk is mitigated by the application context (local desktop tool for microscopy researchers), but shared lab drives make this a realistic vector.

## Findings

- **File:** `src/percell3/segment/roi_import.py:133`
- Post-load validation (lines 135-143) provides zero protection — code executes during `np.load()`
- The Cellpose format requires pickle, so we cannot avoid `allow_pickle=True`

## Proposed Solutions

### Option 1 (Recommended): Add prominent security warning in docstring

```python
def import_cellpose_seg(self, seg_path: Path, ...) -> int:
    """Import a Cellpose ``_seg.npy`` file.

    .. warning::

        This uses ``np.load(allow_pickle=True)`` because the Cellpose
        _seg.npy format requires pickle. Only load files from trusted
        sources. A malicious .npy file can execute arbitrary code.
    """
```

- Pros: Honest, no false sense of security
- Cons: Does not prevent the attack
- Effort: Small
- Risk: Low

### Option 2: Add hash verification

Accept an optional `expected_hash` parameter. Before loading, compute SHA-256 of the file and compare. This protects against tampered files but requires the user to know the expected hash.

- Pros: Defense in depth
- Cons: Adds complexity, users may not have hash available
- Effort: Medium
- Risk: Low

## Acceptance Criteria

- [x] Docstring warns about pickle deserialization risk
- [ ] CLI/UI layers (when implemented) should echo the warning to users

## Work Log

### 2026-02-16 — Code Review Discovery
Identified by security-sentinel agent. Rated CRITICAL for the vulnerability class, but mitigated by application context.

### 2026-02-16 — Fixed (docstring warning)
Added `.. warning::` block to `import_cellpose_seg()` docstring explaining the pickle risk. CLI/UI layer warning deferred to Module 7 implementation.
