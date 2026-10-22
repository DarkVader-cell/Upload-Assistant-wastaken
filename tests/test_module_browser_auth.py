"""Regression: signed-in browser sessions must reach module blueprints."""
# ruff: noqa: S101
import web_ui.server as server


def test_modules_accept_browser_session_without_api_credentials(monkeypatch):
    monkeypatch.setattr(server, '_is_authenticated', lambda: True)
    monkeypatch.setattr(server, '_webui_auth_ok', lambda: False)
    monkeypatch.setattr(server, '_is_ip_allowed', lambda _ip: True)
    client=server.app.test_client()
    for path in ('/upload-library','/remote-upload'):
        response=client.get(path)
        assert response.status_code==200, (path,response.data[:200])
