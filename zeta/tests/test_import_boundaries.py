"""Import boundary tests for package ownership."""

from __future__ import annotations

import ast
from pathlib import Path


def test_zeta_source_does_not_import_commas() -> None:
    root = Path(__file__).resolve().parents[1] / "src"
    offenders: list[str] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "commas" or alias.name.startswith("commas."):
                        offenders.append(f"{path}:{node.lineno}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "commas" or module.startswith("commas."):
                    offenders.append(f"{path}:{node.lineno}")
    assert offenders == []
