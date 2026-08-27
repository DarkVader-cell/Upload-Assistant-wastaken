#!/usr/bin/env python3
"""Prevent new coupling and blocking-resource regressions during refactors."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOTS = (ROOT / "src", ROOT / "web_ui")
SINGLE_FILES = (ROOT / "upload.py",)
LIMITS = {
    "direct_async_clients": 188,
    "direct_async_subprocesses": 16,
    # v3.9 established the current server baseline. Keep the guard strict for
    # future changes while allowing the already-portioned Web UI services.
    "web_ui_server_lines": 6767,
}
LONG_FUNCTION_ALLOWLIST = {
    ("src/region.py", "get_distributor"),
    ("src/trackers/common.py", "unit3d_distributor_ids"),
    # The upstream-compatible CLI parser is intentionally retained as one
    # compatibility entrypoint while smaller parser seams are extracted.
    ("src/args.py", "parse"),
}


def python_files() -> list[Path]:
    files = list(SINGLE_FILES)
    for source_root in SOURCE_ROOTS:
        files.extend(path for path in source_root.rglob("*.py") if "node_modules" not in path.parts)
    return files


def dotted_name(node: ast.AST) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def inspect_sources() -> tuple[dict[str, int], list[str]]:
    counters = {"direct_async_clients": 0, "direct_async_subprocesses": 0}
    violations: list[str] = []
    for path in python_files():
        relative = path.relative_to(ROOT).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError) as error:
            violations.append(f"{relative}: cannot parse: {error}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                called = dotted_name(node.func)
                if called == "httpx.AsyncClient":
                    counters["direct_async_clients"] += 1
                elif called == "asyncio.create_subprocess_exec":
                    counters["direct_async_subprocesses"] += 1
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.end_lineno is not None:
                length = node.end_lineno - node.lineno + 1
                if length > 1000 and (relative, node.name) not in LONG_FUNCTION_ALLOWLIST:
                    violations.append(f"{relative}:{node.lineno} {node.name} is {length} lines")
    counters["web_ui_server_lines"] = len((ROOT / "web_ui" / "server.py").read_text(encoding="utf-8").splitlines())
    return counters, violations


def main() -> int:
    counters, violations = inspect_sources()
    for name, limit in LIMITS.items():
        actual = counters[name]
        print(f"{name}: {actual} (limit {limit})")
        if actual > limit:
            violations.append(f"{name} increased from its migration baseline: {actual} > {limit}")
    if violations:
        print("Architecture guard failed:", file=sys.stderr)
        for violation in violations:
            print(f"  - {violation}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
