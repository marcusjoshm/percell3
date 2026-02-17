---
status: pending
priority: p2
issue_id: "048"
tags: [code-review, segment, quality, simplification]
dependencies: []
---

# `SegmentationParams.to_dict()` Is Fragile Hand-Written Mirror

## Problem Statement

`SegmentationParams.to_dict()` manually enumerates all 9 fields. If a field is added to the dataclass but not to `to_dict()`, it silently drops data from the stored parameters JSON. `dataclasses.asdict()` is a one-line replacement that automatically includes all fields.

## Findings

- **File:** `src/percell3/segment/base_segmenter.py:54-66`
- 12 lines of code that duplicate the field list
- All field values are already JSON-serializable primitives

## Proposed Solutions

Replace with:
```python
def to_dict(self) -> dict[str, Any]:
    return dataclasses.asdict(self)
```

Need to add `import dataclasses` at top of file.

## Acceptance Criteria

- [ ] `to_dict()` uses `dataclasses.asdict(self)`
- [ ] Tests verify all fields are included
- [ ] Unused `import math` removed (already in todo 037)

## Work Log

### 2026-02-16 — Code Review Discovery
Identified by code-simplicity-reviewer.
