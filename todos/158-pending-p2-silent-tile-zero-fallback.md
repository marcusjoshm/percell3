---
status: pending
priority: p2
issue_id: 158
tags: [code-review, quality, io]
dependencies: []
---

# Silent Tile-0 Fallback for Files Without Series Token

## Problem Statement

In `src/percell3/io/engine.py:268-273`, when `tile_config` is set but some files lack series tokens, those files silently merge into tile index 0. This could produce confusing results where tile 0 has multiple files and others have one.

## Findings

- **Source**: kieran-python-reviewer
- **Location**: `src/percell3/io/engine.py:268-273`

```python
for f in ch_files:
    s = f.tokens.get("series")
    if s is not None:
        series_files[int(s)].append(f)
    else:
        series_files[0].append(f)  # silent fallback
```

## Proposed Solutions

### Option A: Raise ValueError when tile_config is set but files lack series tokens
- **Pros**: Fails fast with clear error
- **Cons**: None — this indicates a configuration problem
- **Effort**: Small
- **Risk**: Low

### Option B: Log a warning but continue
- **Pros**: More forgiving
- **Cons**: May produce incorrect stitching silently
- **Effort**: Small
- **Risk**: Medium

## Technical Details

- **Affected files**: `src/percell3/io/engine.py`

## Acceptance Criteria

- [ ] Files without series token raise/warn when tile_config is set
- [ ] Normal non-tile imports unaffected

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-02 | Created from code review | Found by kieran-python-reviewer |
