---
status: pending
priority: p2
issue_id: "046"
tags: [code-review, segment, api-design, agent-native]
dependencies: []
---

# SegmentationResult Lacks Structured Per-Region Stats

## Problem Statement

`SegmentationResult` returns only a total `cell_count` and `warnings: list[str]`. An agent or caller that needs per-region cell counts (e.g., to decide which regions need re-segmentation) must parse free-text warning strings like `"region_001: 0 cells detected"`. There is no structured way to distinguish between "0 cells" warnings and "segmentation crashed" errors.

## Findings

- **File:** `src/percell3/segment/base_segmenter.py:69-85` — SegmentationResult dataclass
- **File:** `src/percell3/segment/_engine.py:134-143` — warnings and errors mixed into same list
- Agent-native reviewer: blocks machine-parseable decision-making
- Kieran-python reviewer: no way to distinguish warning types

## Proposed Solutions

### Option 1 (Recommended): Add `region_stats` field

```python
@dataclass(frozen=True)
class RegionSegmentationStat:
    region_name: str
    cell_count: int
    status: str  # "ok", "warning", "error"
    message: str | None = None

# Add to SegmentationResult:
region_stats: list[RegionSegmentationStat] = field(default_factory=list)
```

Keep `warnings` for backward compatibility.

## Acceptance Criteria

- [ ] Per-region cell counts available in SegmentationResult
- [ ] Errors and warnings distinguishable without string parsing
- [ ] Backward compatible (warnings still populated)

## Work Log

### 2026-02-16 — Code Review Discovery
Identified by agent-native-reviewer and kieran-python-reviewer.
