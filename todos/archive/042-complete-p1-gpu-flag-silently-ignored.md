---
status: pending
priority: p1
issue_id: "042"
tags: [code-review, cli, segment, broken-contract]
dependencies: ["036"]
---

# CLI `--gpu/--no-gpu` Flag Silently Ignored — Broken Feature Contract

## Problem Statement

The `percell3 segment` CLI exposes a `--gpu/--no-gpu` flag (line 15 of `cli/segment.py`) and accepts it as a parameter (line 25), but **never passes it to `SegmentationEngine.run()`**. There is a `# TODO` comment acknowledging this (line 42). Users invoking `--no-gpu` expect CPU-only inference, but `SegmentationParams` defaults `gpu=True`, so Cellpose always attempts GPU. On machines without GPU drivers, this causes a silent fallback or crash.

## Findings

- **File:** `src/percell3/cli/segment.py:15,25,42-43`
- The `gpu` parameter is declared, received, and discarded
- This is worse than no flag: it creates a false promise
- Distinct from todo-036 (which is about engine not exposing all params) — this is specifically about the CLI advertising and discarding a flag

## Proposed Solutions

### Option 1 (Recommended): Remove the flag until the engine supports it
Remove `--gpu/--no-gpu` from the CLI. When todo-036 is resolved (exposing all SegmentationParams), add it back with proper plumbing.

### Option 2: Plumb through immediately
Forward the `gpu` kwarg to `SegmentationEngine.run()` (requires resolving todo-036 first or constructing SegmentationParams in the CLI).

## Acceptance Criteria

- [ ] `--gpu/--no-gpu` flag either removed or correctly plumbed to SegmentationParams
- [ ] No user-visible flag that has zero effect
- [ ] Tests updated accordingly

## Work Log

### 2026-02-16 — Code Review Discovery
Identified by kieran-python-reviewer, code-simplicity-reviewer, and agent-native-reviewer. All flagged independently.
