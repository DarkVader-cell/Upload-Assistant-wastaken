# ruff: noqa: S101

from src.trackers.UNIT3D.blutopia import Blutopia
from src.trackers.UNIT3D.torrentdesi import DesiTorrents


def test_blutopia_banned_groups_include_current_rule_additions_and_raw_exceptions() -> None:
    banned = set(Blutopia.banned_groups)

    assert {"BitHD", "D3US", "mAck", "PAAI", "PHOCiS", "PMi", "PrimeFix", "XDMovies"} <= banned
    assert {"AOC", "CMRG", "EVO", "TERMiNAL", "ViSION"}.isdisjoint(banned)


def test_desitorrents_banned_groups_match_current_rule() -> None:
    assert {"YTS", "RARBG", "BonsaiHD", "GalaxyRG", "-=!DrSTAR!=-", "AKG", "DUS"} <= set(DesiTorrents.banned_groups)
    assert {"DusIcTv", "PDHM", "Ranvijay", "BWT", "DDH", "Telly"} <= set(DesiTorrents.banned_groups)
