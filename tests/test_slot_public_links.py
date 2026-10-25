"""Detail links must be usable without leaking tracker download credentials."""
# ruff: noqa: S101
import pytest

from src.slot_rules.links import linked_entry, public_detail_url


@pytest.mark.parametrize('tracker,prefix',[('AITHER','https://aither.cc/torrents/'),('PASSTHEPOPCORN','https://passthepopcorn.me/torrents.php?torrentid='),('HDBITS','https://hdbits.org/details.php?id=')])
def test_detail_links_use_tracker_routes(tracker,prefix):
    assert linked_entry({'id':42,'name':'Example'},tracker)['link']==prefix+'42'


def test_private_download_url_is_replaced_with_public_detail_link():
    entry=linked_entry({'id':42,'link':'https://aither.cc/api/torrents/42?api_token=SECRET'},'AITHER')
    assert entry['link']=='https://aither.cc/torrents/42'
    assert public_detail_url('javascript:alert(1)') is None
    assert public_detail_url('https://user:password@example.com/details?id=1') is None
    assert public_detail_url('https://example.com/download.php?id=1&passkey=SECRET') is None


def test_no_invented_link_without_torrent_identity():
    assert 'link' not in linked_entry({'name':'No identifier'},'AITHER')
