# ruff: noqa: S101

import asyncio

from src.discparse import DiscParse
from src.meta import Meta


def test_cached_standalone_bd_summary_is_reused_without_full_report(tmp_path) -> None:
    disc_path = tmp_path / "disc" / "BDMV"
    disc_path.mkdir(parents=True)
    save_dir = tmp_path / "tmp" / "release"
    save_dir.mkdir(parents=True)
    summary = "\n".join(
        (
            "Disc Title: Example",
            "Playlist: 00001.MPLS",
            "Disc Size: 1,073,741,824 bytes",
            "Length: 1:30:00.000",
            "Video: MPEG-4 AVC Video / 20000 kbps / 1080p / 23.976 fps / 16:9 / High Profile 4.1 / 8 bits / / BT.709",
        )
    )
    (save_dir / "BD_SUMMARY_00.txt").write_text(summary, encoding="utf-8")
    discs = [{"path": str(disc_path), "type": "BDMV"}]

    parsed_discs, bdinfo = asyncio.run(DiscParse({"DEFAULT": {}}).get_bdinfo(Meta(), discs, "release", str(tmp_path), []))

    assert parsed_discs[0]["summary"] == summary
    assert bdinfo["playlist"] == "00001"
    assert bdinfo["video"][0]["res"] == "1080p"
    assert bdinfo["files"] == []
