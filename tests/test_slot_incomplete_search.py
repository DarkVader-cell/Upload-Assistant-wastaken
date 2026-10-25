# ruff: noqa: S101
import asyncio

import httpx

from src.meta import Meta
from src.slot_rules.base import SlotRules
from src.slot_rules.models import Verdict
from src.slot_rules.registry import SLOT_RULES, evaluate_slots
from src.trackers.UNIT3D.aither import Aither


def test_page_limit_is_not_evidence_of_a_free_slot(monkeypatch):
    calls = []
    class Client:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_args):
            pass
        async def get(self, url, **_kwargs):
            calls.append(url)
            return httpx.Response(200, json={'data':[], 'links':{'next':'https://aither.cc/api/torrents/filter?page=2'}}, request=httpx.Request('GET',url))
    class Rules(SlotRules):
        TRACKER = 'AITHER'
        def decide(self, _upload, _existing):
            return self.decision(Verdict.ALLOW, 'Provisional empty slot')
    monkeypatch.setattr('src.trackers.UNIT3D.httpx.AsyncClient', lambda **_kwargs: Client())
    monkeypatch.setitem(SLOT_RULES, 'AITHER', Rules)
    cfg = {'DEFAULT':{'unit3d_dupe_max_pages':1}, 'TRACKERS':{'AITHER':{'api_key':'fake'}}}
    meta = Meta(category='MOVIE', tmdb=123, resolution='1080p', type='WEBDL')
    rows = asyncio.run(Aither(cfg).search_existing(meta))
    decision = asyncio.run(evaluate_slots(rows,meta,'AITHER',cfg))
    assert len(calls) == 1
    assert decision.verdict is Verdict.REVIEW
    assert decision.requires_evidence
    assert '1-page' in decision.why
    assert not decision.trump_recommended
