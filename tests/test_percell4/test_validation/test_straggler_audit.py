"""AST straggler audit — detect int-typed *_id parameters that should
be bytes UUIDs.

Scans all .py files in src/percell4/ for function parameters whose
name ends with ``_id`` and whose type annotation is ``int``.  These
are potential missed int-to-bytes UUID migration sites.
"""

from __future__ import annotations

import ast
from pathlib import Path

PERCELL4_SRC = Path("src/percell4")

# Parameters that are legitimately int-typed despite ending in _id,
# plus non-ID integer parameters that happen to match the pattern.
ALLOWED_INT_IDS = {
    "label_id",
    "display_order",
    "fov_index",
    "cell_index",
    "roi_index",
    "fkid",
}


def test_no_int_id_parameters():
    """Catch any int *_id parameters that should be bytes UUIDs."""
    violations: list[str] = []
    for py_file in sorted(PERCELL4_SRC.rglob("*.py")):
        try:
            tree = ast.parse(py_file.read_text())
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for arg in node.args.args + node.args.kwonlyargs:
                    if (
                        arg.arg.endswith("_id")
                        and arg.arg not in ALLOWED_INT_IDS
                    ):
                        if arg.annotation and isinstance(
                            arg.annotation, ast.Name
                        ):
                            if arg.annotation.id == "int":
                                violations.append(
                                    f"{py_file}:{node.lineno} "
                                    f"{node.name}({arg.arg}: int)"
                                )

    assert not violations, (
        "Found int *_id parameters that may need bytes UUID:\n"
        + "\n".join(violations)
    )
