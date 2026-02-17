---
status: pending
priority: p2
issue_id: "047"
tags: [code-review, core, performance, sqlite]
dependencies: []
---

# SQLite WAL Mode Missing `PRAGMA synchronous=NORMAL`

## Problem Statement

The database is opened with `PRAGMA journal_mode = WAL` but uses the default `synchronous=FULL`. In WAL mode, `synchronous=NORMAL` is safe against application crashes and provides the same durability guarantees for all practical purposes. Each `conn.commit()` currently triggers an `fsync`, adding 1-10ms per commit. During segmentation of 100 regions, this adds 100-1000ms of pure fsync overhead.

## Findings

- **File:** `src/percell3/core/schema.py:192` — sets WAL mode but not synchronous pragma
- Standard recommendation for WAL + write-heavy workloads (Firefox, Chrome use this)
- Only risk: not crash-safe against OS-level crash (power loss), which is acceptable for a desktop analysis tool

## Proposed Solutions

Add one line after the WAL mode pragma:
```python
conn.execute("PRAGMA synchronous = NORMAL")
```

## Acceptance Criteria

- [ ] `PRAGMA synchronous = NORMAL` set alongside WAL mode
- [ ] All existing tests pass
- [ ] Document the trade-off in a code comment

## Work Log

### 2026-02-16 — Code Review Discovery
Identified by performance-oracle.
