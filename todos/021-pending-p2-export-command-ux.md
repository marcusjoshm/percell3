---
status: pending
priority: p2
issue_id: "021"
tags: [code-review, cli, performance, ux]
dependencies: []
---
# Export Command Missing UX and Safety Features

## Problem Statement
The export command lacks progress feedback, overwrite protection, and filtering options that the underlying API supports. For large experiments, export can take minutes with no output, and can silently overwrite existing files.

## Findings

### 1. No progress feedback
- `export.py:19-27`: No progress bar or spinner during export
- For large experiments (500K+ cells), export can take minutes with zero output
- Compare with import_cmd.py which has a proper Rich progress bar

### 2. No overwrite protection
- `export.py:23`: `out_path = Path(output)` → writes directly, no existence check
- User could accidentally overwrite important files (e.g., `percell3 export ~/.bashrc`)
- Menu path (`menu.py:364`) calls `.expanduser()` but CLI path doesn't — inconsistent

### 3. No filtering options exposed
- `ExperimentStore.export_csv()` accepts `channels` and `metrics` parameters
- CLI export command passes no filtering options through
- Users must export everything or fall back to Python API

### 4. Unbounded memory for large exports
- `export_csv()` materializes entire measurement dataset into memory via pandas
- For 500K cells × 20 channels = 10M rows, can consume 4-8 GB RAM
- No streaming or chunked writing option

**Source:** performance-oracle CRITICAL-2/3, security-sentinel MEDIUM-3, agent-native-reviewer WARNING-4

## Proposed Solutions
### Option A: Add progress + overwrite check + filters (Recommended)
Add a Rich spinner during export, check for existing file before overwrite, add --channels/--metrics options, add .expanduser() consistently.

Pros: Better UX, safer, more useful
Cons: More code in export.py
Effort: Small-Medium

### Option B: Also add chunked/streaming export
Option A plus refactor export_csv to use chunked SQL queries and streaming CSV writing.

Pros: Handles arbitrarily large experiments
Cons: Requires changes to core module's export_csv
Effort: Medium-Large

## Acceptance Criteria
- [ ] Export shows progress spinner during operation
- [ ] Export warns before overwriting existing files
- [ ] --channels and --metrics filter options available
- [ ] .expanduser() applied consistently in CLI and menu paths
- [ ] All existing tests pass

## Work Log
### 2026-02-13 - Code Review Discovery
Three reviewers flagged export UX issues from different angles (performance, security, agent-native).
