"""Architecture boundary tests — verify hexagonal architecture invariants.

Uses AST parsing to ensure external modules never import forbidden
core internals (experiment_db, layer_store, schema) directly.
"""

from __future__ import annotations

import ast
from pathlib import Path

PERCELL4_SRC = Path("src/percell4")

# Modules that should ONLY import from core via experiment_store
# (not experiment_db, layer_store, schema directly)
EXTERNAL_MODULES = ["measure", "segment", "io", "plugins", "workflow", "cli"]
FORBIDDEN_CORE_IMPORTS = {"experiment_db", "layer_store", "schema"}


def _collect_core_imports(py_file: Path) -> list[tuple[str, int]]:
    """Parse *py_file* and return (module_name, lineno) for every
    ``from percell4.core.<module> import ...`` statement.
    """
    try:
        tree = ast.parse(py_file.read_text())
    except SyntaxError:
        return []

    results: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("percell4.core."):
                # Extract the sub-module name after "percell4.core."
                parts = node.module.split(".")
                if len(parts) >= 3:
                    sub = parts[2]
                    results.append((sub, node.lineno))
    return results


def test_external_modules_respect_boundary():
    """No .py file in EXTERNAL_MODULES may import experiment_db,
    layer_store, or schema from percell4.core directly.
    """
    violations: list[str] = []
    for module_name in EXTERNAL_MODULES:
        module_dir = PERCELL4_SRC / module_name
        if not module_dir.is_dir():
            continue
        for py_file in sorted(module_dir.rglob("*.py")):
            imports = _collect_core_imports(py_file)
            for sub_module, lineno in imports:
                if sub_module in FORBIDDEN_CORE_IMPORTS:
                    violations.append(
                        f"{py_file}:{lineno} imports percell4.core.{sub_module}"
                    )

    assert not violations, (
        "External modules import forbidden core internals:\n"
        + "\n".join(violations)
    )


def test_experiment_store_is_only_facade():
    """experiment_store.py must import experiment_db and layer_store
    (it is the facade that wraps them).
    """
    store_path = PERCELL4_SRC / "core" / "experiment_store.py"
    assert store_path.exists(), f"Missing {store_path}"

    imports = _collect_core_imports(store_path)
    imported_modules = {sub for sub, _ in imports}

    assert "experiment_db" in imported_modules, (
        "experiment_store.py does not import experiment_db — "
        "it should be the facade"
    )
    assert "layer_store" in imported_modules, (
        "experiment_store.py does not import layer_store — "
        "it should be the facade"
    )
