---
status: complete
priority: p1
issue_id: "045"
tags: [code-review, segment, security]
dependencies: []
---

# Unvalidated Cellpose Model Name Enables Arbitrary Code Execution

## Problem Statement

The `--model` CLI option accepts any free-form string, which is passed directly to Cellpose's `CellposeModel(model_type=model_name)`. Cellpose treats unrecognized model names as filesystem paths and loads them via `torch.load()`, which uses pickle deserialization internally. A user (or attacker on a shared server) can pass `--model /path/to/malicious.pth` to execute arbitrary code.

## Findings

- **CLI:** `src/percell3/cli/segment.py:13` — `--model` has no validation
- **Adapter:** `src/percell3/segment/cellpose_adapter.py:48-51` — passes directly to Cellpose constructor
- Cellpose 3.x and 4.x both accept filesystem paths as `model_type`
- `torch.load()` uses pickle internally -> arbitrary code execution

## Proposed Solutions

### Option 1 (Recommended): Allowlist known Cellpose models in CLI

```python
KNOWN_MODELS = ["cyto", "cyto2", "cyto3", "nuclei", "tissuenet", "livecell"]

@click.option(
    "--model",
    default="cyto3",
    type=click.Choice(KNOWN_MODELS, case_sensitive=False),
    help="Cellpose model name.",
)
```

### Option 2: Validate model name contains no path separators

```python
if "/" in model_name or "\\" in model_name or ".." in model_name:
    raise ValueError(f"Invalid model name: {model_name!r}")
```

## Acceptance Criteria

- [ ] Model name validated against allowlist or sanitized before passing to Cellpose
- [ ] `--model ../evil` raises a clear error
- [ ] Python API also validates (not just CLI)

## Work Log

### 2026-02-16 — Code Review Discovery
Identified by security-sentinel. Arbitrary code execution via torch.load pickle deserialization.
