"""The layering in docs/structure.md section 2, enforced on the import graph."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "iphone_archive"
# Lower layers may never import these higher ones.
FORBIDDEN = {
    "core": {"service", "gui", "browse", "cli"},
    "catalog": {"service", "gui", "browse", "cli"},
    "device": {"service", "gui", "browse", "cli"},
}


def layering_imported_packages(path: Path) -> set[str]:
    """Return the top-level ``iphone_archive`` subpackages a module imports."""
    package = path.relative_to(PACKAGE).parts[0]
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module and node.module.startswith("iphone_archive."):
                found.add(node.module.split(".")[1])
            elif node.level == 1:
                found.add(package)
            elif node.level == 2 and node.module:
                found.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("iphone_archive."):
                    found.add(alias.name.split(".")[1])
    return found


@pytest.mark.parametrize("layer", sorted(FORBIDDEN))
def test_lower_layers_never_import_higher_ones(layer):
    """core, catalog and device stay usable without the service or any front end."""
    offenders = {
        module.relative_to(PACKAGE).as_posix(): sorted(
            layering_imported_packages(module) & FORBIDDEN[layer]
        )
        for module in (PACKAGE / layer).glob("*.py")
    }
    assert {name: bad for name, bad in offenders.items() if bad} == {}
