# ruff: noqa: S101
from src import webui_events


def test_structured_slot_event_keeps_specific_evidence_and_safe_links(monkeypatch):
    events = []
    monkeypatch.setattr(webui_events, 'enabled', lambda: True)
    monkeypatch.setattr(webui_events, '_emit', lambda kind, payload: events.append((kind,payload)))
    webui_events.slot('AITHER','review','Review','Incomplete metadata',why='Missing HDR metadata',conflicts=[{'id':42,'name':'Existing release','link':'https://aither.cc/api/torrents/42?api_token=SECRET','traits':'1080p H.265','reason':'HDR package unknown'}],requirements=['Read MediaInfo'],protected_ids=['42'],related_releases=[{'id':7,'name':'Other master','reason':'Context only'}])
    kind, payload = events[0]
    assert kind == 'slot'
    assert payload['conflicts'][0]['link'] == 'https://aither.cc/torrents/42'
    assert payload['conflicts'][0]['reason'] == 'HDR package unknown'
    assert payload['conflicts'][0]['traits'] == '1080p H.265'
    assert payload['protected_ids'] == ['42']
    assert payload['requirements'] == ['Read MediaInfo']
    assert payload['related_releases'][0]['link'] == 'https://aither.cc/torrents/7'
    assert 'SECRET' not in str(payload)
