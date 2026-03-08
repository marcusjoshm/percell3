---
status: complete
priority: p3
issue_id: "082"
tags: [plan-review, cli, ux]
dependencies: []
---

# Bio-Rep Short Flag: Use `-b` Not `-n`

## Problem Statement

The plan proposes `-n` as the short flag for `--bio-rep`. `-n` universally suggests "number" or "count" (head -n, xargs -n). `-b` is more intuitive for bio-rep.

## Findings

Simplicity reviewer flagged this as unintuitive. `-b` has no conflicts in the current CLI.

## Proposed Solutions

### A) Change short flag from `-n` to `-b`

- **Effort:** Trivial
- **Risk:** None

Update the CLI option definition to use `-b` / `--bio-rep` instead of `-n` / `--bio-rep`.

## Technical Details

The change is a single-line edit in the Click option decorator for any command that accepts `--bio-rep`.

## Acceptance Criteria

- [ ] Plan updated: `-b` / `--bio-rep` instead of `-n` / `--bio-rep`

## Work Log

_No work performed yet._

## Resources

- Plan review: simplicity reviewer feedback
