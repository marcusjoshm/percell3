---
status: pending
priority: p3
issue_id: "101"
tags: [code-review, cli, agent-native, bio-rep]
dependencies: []
---

# No CLI Command to Add Bio Reps Independently

## Problem Statement

The only ways to create a bio rep are: (a) default "N1" from `create_schema()`, and (b) as a side effect of `import`. There is no standalone `percell3 add bio-rep <name>` CLI command. Programmatic callers can use `store.add_bio_rep()`, but CLI users cannot set up bio reps before importing.

## Findings

- **Found by:** agent-native-reviewer

## Proposed Solutions

### Solution A: Add subcommand under `query` or new `manage` group
- `percell3 manage add-bio-rep <name> -e <experiment>`
- **Effort:** Small | **Risk:** Low

## Work Log

- 2026-02-17: Identified during code review
