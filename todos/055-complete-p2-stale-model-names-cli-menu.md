---
status: complete
priority: p2
issue_id: "055"
tags: [code-review, segment, cli, ux, scientific-integrity]
dependencies: ["054"]
---

# CLI and Menu Display Stale Model Names (cyto3/nuclei Not Available in Cellpose 4.x)

## Problem Statement

The CLI and interactive menu advertise model names that don't exist in Cellpose 4.x:

- CLI: `--model` defaults to `cyto3`, help text doesn't mention `cpsam`
- Menu: "Common models: cyto3, cyto2, nuclei, cyto" — none are real 4.x models
- Menu `Prompt.ask` accepts arbitrary text without validating against allowlist

Users are misled into thinking they can choose between models when Cellpose 4.x only ships `cpsam`.

## Findings

- `src/percell3/cli/segment.py:20` — `default="cyto3"`, no `click.Choice` validation
- `src/percell3/cli/menu.py:304-306` — hardcoded `common_models = ["cyto3", "cyto2", "nuclei", "cyto"]`
- `src/percell3/cli/menu.py:306` — `Prompt.ask("Model", default="cyto3")` — no `choices=` restriction
- `src/percell3/segment/base_segmenter.py:30` — `model_name: str = "cyto3"` default
- `src/percell3/segment/_engine.py:40` — `model: str = "cyto3"` default

## Proposed Solutions

### Option 1 (Recommended): Update defaults and add click.Choice

Update all defaults to `"cpsam"` and constrain CLI input:

```python
# cli/segment.py
from percell3.segment.cellpose_adapter import KNOWN_CELLPOSE_MODELS

@click.option(
    "--model", default="cpsam", show_default=True,
    type=click.Choice(sorted(KNOWN_CELLPOSE_MODELS), case_sensitive=False),
    help="Cellpose model name.",
)
```

```python
# cli/menu.py
common_models = ["cpsam"]  # Only model in Cellpose 4.x
console.print("\n[bold]Available model:[/bold] cpsam (Cellpose-SAM)")
model = Prompt.ask("Model", default="cpsam")
```

- Pros: Honest UX, tab completion, early validation
- Cons: Less discoverable for 3.x users
- Effort: Small
- Risk: Low

## Acceptance Criteria

- [x] CLI default model is `cpsam`
- [x] CLI uses `click.Choice(KNOWN_CELLPOSE_MODELS)` for `--model`
- [x] Menu shows accurate model list for installed Cellpose version
- [x] All parameter defaults updated from `cyto3` to `cpsam`

## Work Log

### 2026-02-16 — Code Review Discovery
Identified during review. Depends on todo-054 (add `cpsam` to allowlist first).

### 2026-02-16 — Implementation
Fixed alongside todo-054 on branch `fix/cellpose4-adapter-migration`:
- CLI `--model` default changed to `cpsam` with `click.Choice` validation
- Menu model display updated: shows `cpsam (Cellpose-SAM, default for Cellpose 4.x)`
- Workflow step `Segment` model choices updated to include `cpsam` as default
- All parameter defaults updated from `cyto3` to `cpsam`
