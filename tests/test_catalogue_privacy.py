# ruff: noqa: S101
"""Prevent accidental reintroduction of an Internet-facing dashboard listener."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_public_nginx_template_denies_instead_of_proxying():
    template = (ROOT / "docs/catalogue-nginx.conf").read_text()
    assert "proxy_pass" not in template
    assert "location = /catalogue" in template
    assert "location ^~ /catalogue/" in template
    assert template.count("return 404;") == 2


def test_dashboard_listener_is_explicitly_loopback_only():
    tree = ast.parse((ROOT / "src/catalogue_web.py").read_text())
    listeners = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "run_app"]
    assert len(listeners) == 1
    host = next(keyword.value for keyword in listeners[0].keywords if keyword.arg == "host")
    assert isinstance(host, ast.Constant) and host.value == "127.0.0.1"
