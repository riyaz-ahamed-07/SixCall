from __future__ import annotations

import ast
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1] / "app" / "agent"


def test_agent_package_does_not_import_store():
    offenders: list[str] = []
    for path in AGENT_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "store" or alias.name.startswith("app.store"):
                        offenders.append(f"{path.name}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod == "store" or mod.startswith("app.store") or mod.startswith("store."):
                    offenders.append(f"{path.name}: from {mod}")
                # relative import of store package
                if mod == "" and any(a.name == "store" for a in node.names):
                    offenders.append(f"{path.name}: from . import store")
    assert offenders == []
