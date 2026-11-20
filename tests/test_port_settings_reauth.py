# ruff: noqa: S101, S105
import time

from web_ui import server


def test_reauth_required_and_expires(monkeypatch):
    state = {}
    monkeypatch.setattr(server, "_session_get", lambda key, default=None: state.get(key, default))
    monkeypatch.setattr(server, "_account_fingerprint_matches", lambda value: value == "fingerprint")
    monkeypatch.setattr(server, "_totp_enabled", lambda: False)
    with server.app.test_request_context():
        assert server._settings_reauth_required_response().status_code == 403
        state["settings_reauth"] = {"until": time.time() + 60, "account": "fingerprint", "totp": False}
        assert server._settings_reauth_required_response() is None
        state["settings_reauth"]["until"] = time.time() - 1
        assert server._settings_reauth_required_response().status_code == 403


def test_reauth_endpoint_requires_password_and_records_confirmation(monkeypatch):
    recorded = {}
    monkeypatch.setattr(server, "_is_authenticated", lambda: True)
    monkeypatch.setattr(server, "_verify_csrf_header", lambda: True)
    monkeypatch.setattr(server, "_verify_same_origin", lambda: True)
    monkeypatch.setattr(server, "_load_user_record", lambda: {"username": "test"})
    monkeypatch.setattr(server, "_account_fingerprint", lambda: "fingerprint")
    monkeypatch.setattr(server, "_account_fingerprint_matches", lambda value: value == "fingerprint")
    monkeypatch.setattr(server, "_totp_enabled", lambda: False)
    monkeypatch.setattr(server.auth_mod, "verify_user", lambda username, password: username == "test" and password == "correct")
    monkeypatch.setattr(server, "_session_set", lambda key, value: recorded.update({key: value}))
    client = server.app.test_client()
    assert client.post("/api/settings_reauth", json={"password": "wrong"}).status_code == 400
    assert recorded == {}
    assert client.post("/api/settings_reauth", json={"password": "correct"}).status_code == 200
    assert recorded["settings_reauth"]["account"] == "fingerprint"


def test_saved_credentials_are_redacted_and_placeholder_cannot_be_saved():
    path = ["TORRENT_CLIENTS", "client", "qbit_pass"]
    assert server._redact_config_value(path, "secret", "") == server.REDACTED_PLACEHOLDER
    assert server._find_redacted_sensitive_path(path, server.REDACTED_PLACEHOLDER) == path


def test_saved_client_credentials_require_exact_destination():
    saved = {"torrent_client": "qbit", "qbit_url": "https://safe.example", "qbit_pass": "secret"}
    draft = {**saved, "qbit_pass": server.REDACTED_PLACEHOLDER}
    assert server._destination_matches(draft, saved)
    assert server._restore_redacted_values(draft, saved)["qbit_pass"] == "secret"
    draft["qbit_url"] = "https://other.example"
    assert not server._destination_matches(draft, saved)


def test_reauth_rejects_changed_second_factor(monkeypatch):
    monkeypatch.setattr(server, "_session_get", lambda *_: {"until": time.time() + 60, "account": "fingerprint", "totp": False})
    monkeypatch.setattr(server, "_account_fingerprint_matches", lambda value: value == "fingerprint")
    monkeypatch.setattr(server, "_totp_enabled", lambda: True)
    assert not server._settings_reauth_valid()
