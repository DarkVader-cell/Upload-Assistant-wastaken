import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask

from web_ui.services.comparisons import create_comparison_blueprint, validate_request


@pytest.fixture
def sources(tmp_path):
    files = [tmp_path / f"source-{i}.mkv" for i in range(2)]
    for file in files:
        file.write_bytes(b"synthetic")
    return {"sources": [{"path": str(f), "label": f"Source {i}", "offset": 0, "tonemap": "auto"} for i, f in enumerate(files)], "count": 2, "frames": []}


def test_comparison_validation(sources):
    result = validate_request(sources, lambda path, **kw: str(Path(path).resolve()))
    assert len(result["sources"]) == 2
    assert result["sources"][0]["tonemap"] == "auto"


@pytest.mark.parametrize("key,value", [("count", 0), ("count", 9), ("count", True), ("frames", [-1]), ("frames", [False]), ("frames", [0] * 9)])
def test_invalid_frame_settings(sources, key, value):
    sources[key] = value
    with pytest.raises(ValueError):
        validate_request(sources, lambda p, **kw: p)


@pytest.mark.parametrize("key,value", [("offset", -1), ("offset", True), ("tonemap", "shell"), ("label", "x\ny"), ("path", "/does-not-exist.mkv")])
def test_invalid_source_settings(sources, key, value):
    sources["sources"][0][key] = value
    with pytest.raises(ValueError):
        validate_request(sources, lambda p, **kw: p)


def test_path_resolver_is_mandatory(sources):
    def reject(*args, **kwargs):
        raise ValueError("outside roots")
    with pytest.raises(ValueError):
        validate_request(sources, reject)


def make_app(tmp_path, monkeypatch, security):
    script = tmp_path / "multi_comps.vpy"
    script.write_text("# independently installed")
    monkeypatch.setenv("UA_COMPARISON_PYTHON", sys.executable)
    monkeypatch.setenv("UA_COMPARISON_SCRIPT", str(script))
    app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[1] / "web_ui/templates"))
    app.register_blueprint(create_comparison_blueprint(authenticated=lambda: security["auth"], csrf_valid=lambda: security["csrf"], same_origin=lambda: security["origin"], csrf_token=lambda: "synthetic", resolve_path=lambda p, **kw: p, state_root=tmp_path, code_root=tmp_path))
    return app


@pytest.mark.parametrize("security,status", [({"auth": False, "csrf": True, "origin": True}, 401), ({"auth": True, "csrf": False, "origin": True}, 403), ({"auth": True, "csrf": True, "origin": False}, 403)])
def test_authenticated_csrf_and_origin_required(tmp_path, monkeypatch, sources, security, status):
    app = make_app(tmp_path, monkeypatch, security)
    assert app.test_client().post("/api/comparisons", json=sources).status_code == status


def test_render_job_outputs_and_zip_are_confined(tmp_path, monkeypatch, sources):
    app = make_app(tmp_path, monkeypatch, {"auth": True, "csrf": True, "origin": True})
    def render(argv, **kwargs):
        assert kwargs.get("shell") is not True
        assert kwargs["timeout"] == 1800
        directory = Path(argv[2]).parent
        job = json.loads(Path(argv[2]).read_text())
        assert job["sources"][0]["path"] == sources["sources"][0]["path"]
        name = "001-01-Source.png"
        (directory / name).write_bytes(b"synthetic png")
        (directory / "manifest.json").write_text(json.dumps({"files": [{"name": name}], "frames": [5], "sources": sources["sources"]}))
    monkeypatch.setattr("web_ui.services.comparisons.subprocess.run", render)
    monkeypatch.setattr("web_ui.services.comparisons.threading.Thread", lambda target, args, **kw: SimpleNamespace(start=lambda: target(*args)))
    client = app.test_client()
    response = client.post("/api/comparisons", json=sources)
    assert response.status_code == 202
    job_id = response.json["id"]
    assert client.get(f"/api/comparisons/{job_id}").json["status"] == "completed"
    assert client.get(f"/api/comparisons/{job_id}/comparisons.zip").status_code == 200
    assert client.get(f"/api/comparisons/{job_id}/job.json").status_code == 404
    assert client.get("/api/comparisons/not-a-job/comparisons.zip").status_code == 404
    import io
    import zipfile
    with zipfile.ZipFile(io.BytesIO(client.get(f"/api/comparisons/{job_id}/comparisons.zip").data)) as archive:
        assert str(tmp_path) not in archive.read("manifest.json").decode()


def test_comparison_renderer_failure_is_sanitized(tmp_path, monkeypatch, sources):
    app = make_app(tmp_path, monkeypatch, {"auth": True, "csrf": True, "origin": True})
    monkeypatch.setattr("web_ui.services.comparisons.subprocess.run", Mock(side_effect=RuntimeError("private data")))
    monkeypatch.setattr("web_ui.services.comparisons.threading.Thread", lambda target, args, **kw: SimpleNamespace(start=lambda: target(*args)))
    client = app.test_client()
    job_id = client.post("/api/comparisons", json=sources).json["id"]
    response = client.get(f"/api/comparisons/{job_id}")
    assert response.json["status"] == "failed"
    assert "private data" not in response.text
    assert client.get(f"/api/comparisons/{job_id}/comparisons.zip").status_code == 404
