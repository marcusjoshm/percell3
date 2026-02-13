---
status: pending
priority: p3
issue_id: "014"
tags: [code-review, quality]
dependencies: []
---
# No Introspection Methods for Tags/Runs/Metrics

## Problem Statement
Tags, segmentation runs, threshold runs, and analysis runs are write-only from the ExperimentStore API. There are no retrieval methods to inspect what has been recorded, limiting debuggability and interactive exploration.

## Findings
- Store has methods to create/write tags, segmentation runs, threshold runs, and analysis runs
- No corresponding `get_tags()`, `get_segmentation_runs()`, `get_available_metrics()` methods exist
- Users cannot inspect the current state of these entities without raw SQL queries
- This makes debugging workflows and building UIs significantly harder

## Proposed Solutions
### Option 1
Add retrieval methods for each entity type:
- `get_tags(region_id: int | None = None) -> list[str]`
- `get_segmentation_runs() -> list[SegmentationRunInfo]`
- `get_threshold_runs() -> list[ThresholdRunInfo]`
- `get_analysis_runs() -> list[AnalysisRunInfo]`
- `get_available_metrics() -> list[str]`

## Acceptance Criteria
- [ ] Retrieval method exists for tags
- [ ] Retrieval method exists for segmentation runs
- [ ] Retrieval method exists for threshold runs
- [ ] Retrieval method exists for analysis runs
- [ ] Retrieval method exists for available metrics
- [ ] Each method has a corresponding unit test

## Work Log
### 2026-02-12 - Code Review Discovery
