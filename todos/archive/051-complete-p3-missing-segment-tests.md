---
status: pending
priority: p3
issue_id: "051"
tags: [code-review, segment, testing]
dependencies: []
---

# Missing Tests: Happy-Path CLI Segment, Region Error Handling

## Problem Statement

Two test gaps: (1) `test_cli/test_segment.py` has only error-path tests (help, missing experiment, missing channel) but no happy-path test that verifies a successful segmentation through the CLI with a mocked segmenter. (2) `test_segment/test_engine.py` has no test for per-region error handling (the `except Exception` path at `_engine.py:139`).

## Findings

- `tests/test_cli/test_segment.py`: 3 tests, all error paths. Compare to `test_import.py` which has `test_import_basic`.
- `tests/test_segment/test_engine.py`: No test with a `FailingSegmenter` mock to verify continue-on-error behavior.
- Also: `test_base_segmenter.py:130-173` has tests that duplicate conftest mock and test ABC machinery (not application logic). `test_cellpose_adapter.py:72-84` has a tautological test.

## Proposed Solutions

1. Add `test_segment_basic` happy-path CLI test with mocked segmenter
2. Add `test_region_failure_continues` with a mock that fails on specific regions
3. Optionally: remove tautological tests and ABC-machinery tests

## Acceptance Criteria

- [ ] Happy-path CLI segmentation test exists
- [ ] Region error handling tested (engine continues, warnings populated)

## Work Log

### 2026-02-16 — Code Review Discovery
Identified by kieran-python-reviewer and code-simplicity-reviewer.
