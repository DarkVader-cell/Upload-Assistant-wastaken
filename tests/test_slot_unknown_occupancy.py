# ruff: noqa: S101
from src.slot_rules.base import SlotRules
from src.slot_rules.models import Verdict
from src.slot_rules.profile import ReleaseProfile


class Rules(SlotRules):
    TRACKER = 'TEST'
    def key(self, profile):
        return self.require(profile.resolution, 'resolution'), self.require(profile.codec, 'video codec')
    def decide(self, upload, existing):
        return self.by_slot(upload, existing, self.key, '1080p H.265', trump=lambda _a, _b: (Verdict.ALLOW, 'Documented replacement benefit'))


def profile(name, id_, codec='H265', resolution='1080p'):
    return ReleaseProfile(name=name, kind='WEBDL', resolution=resolution, codec=codec, hdr=frozenset(), entry={'id':id_, 'name':name, 'link':f'https://tracker.example/torrents/{id_}'})


def test_unknown_competitor_prevents_false_trump_permission():
    decision = Rules().evaluate(profile('new', 0), [profile('known',1), profile('unknown',2,codec=None)])
    assert decision.verdict is Verdict.REVIEW
    assert decision.requires_evidence
    assert not decision.trump_recommended
    assert decision.conflicts[0]['id'] == 2
    assert 'codec' in decision.comparisons[0]['reason']
    assert decision.related_releases[0]['id'] == 1


def test_unknown_codec_at_independently_different_resolution_does_not_block():
    decision = Rules().evaluate(profile('new',0), [profile('known',1),profile('other resolution',2,codec=None,resolution='720p')])
    assert decision.verdict is Verdict.ALLOW
    assert decision.trump_recommended
