from __future__ import annotations

import ast
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1] / "app" / "agent"


def test_agent_package_does_not_import_store():
    offenders: list[str] = []
    banned_prefixes = ("app.store", "app.index", "store", "store.", "app.index.")
    for path in AGENT_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name
                    if name in {"store", "index"} or name.startswith("app.store") or name.startswith("app.index"):
                        offenders.append(f"{path.name}: import {name}")
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod in {"store", "index"} or any(mod.startswith(p) for p in banned_prefixes):
                    offenders.append(f"{path.name}: from {mod}")
                if mod == "" and any(a.name in {"store", "index"} for a in node.names):
                    offenders.append(f"{path.name}: from . import store/index")
    assert offenders == []
