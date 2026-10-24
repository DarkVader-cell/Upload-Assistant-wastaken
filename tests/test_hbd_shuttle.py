"""No live qB/SSH: raw staging, exact piece proof, and deletion safety."""

# ruff: noqa: S101
import hashlib
import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("hbd_shuttle", Path(__file__).parents[1] / "tools/hbd-shuttle.py")
s = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(s)


def be(x):
    if isinstance(x, int):
        return b"i" + str(x).encode() + b"e"
    if isinstance(x, bytes):
        return str(len(x)).encode() + b":" + x
    if isinstance(x, list):
        return b"l" + b"".join(be(i) for i in x) + b"e"
    return b"d" + b"".join(be(k) + be(v) for k, v in sorted(x.items())) + b"e"


def torrent(data=b"abcdefghijk", name=b"renamed.mkv"):
    pieces = b"".join(hashlib.sha1(data[i : i + 4], usedforsecurity=False).digest() for i in range(0, len(data), 4))
    info = {b"name": name, b"length": len(data), b"piece length": 4, b"pieces": pieces, b"private": 1}
    return be({b"announce": b"https://example.invalid/announce", b"info": info}), hashlib.sha1(be(info), usedforsecurity=False).hexdigest()


@pytest.mark.parametrize("bad", ["../x", "/etc/passwd", "a/../x", "a//b", "a\\b", "C:/x", "x\ny", "./x"])
def test_reject_traversal_and_control_paths(bad):
    with pytest.raises(s.Refuse):
        s.safe_relative(bad)


def test_symlink_parent_is_not_resolved_away(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(s.Refuse):
        s.confined(root, root / "link" / "x")


def test_raw_file_manifest_needs_no_torrent(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    f = root / "raw.mkv"
    f.write_bytes(b"raw video")
    assert s.manifest(f, [root])[0]["source"] == str(f)
    (root / "link.mkv").symlink_to(f)
    with pytest.raises(s.Refuse):
        s.manifest(root, [root])


def test_exact_piece_proof_not_name_or_size(tmp_path):
    raw, h = torrent()
    p = tmp_path / "original.mkv"
    p.write_bytes(b"abcdefghijk")
    assert s.torrent_files(raw, h) == [("renamed.mkv", 11)]
    assert s.verify_pieces(raw, [p], [hashlib.sha256(p.read_bytes()).hexdigest()])
    p.write_bytes(b"Abcdefghijk")
    with pytest.raises(s.Refuse, match="piece mismatch"):
        s.verify_pieces(raw, [p])
    with pytest.raises(s.Refuse, match="infohash"):
        s.torrent_files(raw, "0" * 40)


def test_cross_file_pieces(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.write_bytes(b"abc")
    b.write_bytes(b"defgh")
    info = {
        b"name": b"pack",
        b"files": [{b"path": [b"a"], b"length": 3}, {b"path": [b"b"], b"length": 5}],
        b"piece length": 4,
        b"pieces": hashlib.sha1(b"abcd", usedforsecurity=False).digest() + hashlib.sha1(b"efgh", usedforsecurity=False).digest(),
    }
    assert s.verify_pieces(be({b"info": info}), [a, b])


def test_dedi_inventory_and_api_deletion_are_bounded():
    qb = s.QB.__new__(s.QB)
    qb.role = "dedi"
    with pytest.raises(s.Refuse, match="Unfiltered"):
        qb.call("torrents/info")
    with pytest.raises(s.Refuse, match="Exactly one"):
        qb.call("torrents/delete", {"hashes": "all", "deleteFiles": "false"}, post=True)
    with pytest.raises(s.Refuse, match="payload"):
        qb.call("torrents/delete", {"hashes": "a" * 40, "deleteFiles": "true"}, post=True)


def test_worker_checksum_failure_keeps_copy(tmp_path):
    cfg = {"stage_root": str(tmp_path / "ssd")}
    id_ = "a" * 32
    files = [{"relative": "raw.mkv", "size": 3, "sha256": "wrong"}]
    payload = Path(s.rpc(cfg, {"action": "prepare", "id": id_, "files": files}))
    (payload / "raw.mkv").write_bytes(b"abc")
    with pytest.raises(s.Refuse, match="checksum"):
        s.rpc(cfg, {"action": "commit", "record": {"id": id_, "files": files}})
    assert (payload / "raw.mkv").read_bytes() == b"abc"


@pytest.mark.parametrize('unexpected_recheck', [False, True])
def test_return_reannounce_proof_then_registration_only_delete(tmp_path, monkeypatch, unexpected_recheck):
    data = b"abcdefghijk"
    raw, hash_ = torrent(data)
    original = tmp_path / "raw.mkv"
    original.write_bytes(data)
    target_root = tmp_path / "dedi-links"
    target_root.mkdir()
    events = []
    src = {
        "hash": hash_,
        "name": "Renamed title",
        "save_path": "/ssd/Uploads",
        "state": "uploading",
        "progress": 1,
        "amount_left": 0,
        "category": "Uploads",
        "tags": "BLU, shared",
        "auto_tmm": False,
        "up_limit": 2048,
        "dl_limit": 4096,
        "ratio_limit": 3.0,
        "seeding_time_limit": 72,
        "inactive_seeding_time_limit": -2,
    }
    trackers = [{"url": "https://example.invalid/announce", "tier": 0}]

    class FakeTarget:
        info_ = None

        def info(self, h):
            assert h == hash_
            return self.info_

        def call(self, path, args=None, **kw):
            if path == "torrents/categories":
                return {}
            if path == "torrents/trackers":
                return trackers
            if path == "torrents/add":
                assert "proof" in events and kw["torrent"] == raw and args["skip_checking"] == "true"
                events.append("add")
                self.info_ = {**src, "save_path": args["savepath"], "category": args["category"], "tags": args["tags"], "state": "checkingUP" if unexpected_recheck else "stoppedUP"}
                return b"Ok."
            raise AssertionError(path)

        def post(self, path, **_kw):
            assert path != 'torrents/recheck'
            events.append(path)
            if path == 'torrents/delete':
                assert _kw['deleteFiles'] == 'false'
                self.info_ = None

        def state(self, _h, _start):
            events.append("dedi-start" if _start else "dedi-stop")
            self.info_["state"] = "uploading" if _start else "stoppedUP"

    target = FakeTarget()

    class FakePeer:
        def qb(self, path, args=None, **_kw):
            if path == "torrents/info":
                return [src]
            if path == "torrents/export":
                return raw
            if path == "torrents/files":
                return [{"name": "renamed.mkv", "size": len(data), "priority": 1}]
            if path == "torrents/trackers":
                return trackers
            if path == "torrents/reannounce":
                events.append("reannounce")
                return b""
            if path == "torrents/stop":
                events.append("ssd-stop")
                return b""
            if path == "torrents/delete":
                assert args["deleteFiles"] == "false" and s.complete(target.info_)
                assert "proof" in events and "dedi-start" in events
                events.append("source-registration-delete")
                return b""
            raise AssertionError(path)

        def rpc(self, action, **_kw):
            assert action == "inspect"
            return [{"path": "/ssd/Uploads/renamed.mkv", "size": len(data), "origin": ["a" * 32, "raw.mkv"], "inode": [1, 2]}]

    cfg = {"state_dir": str(tmp_path / "state"), "return_root": str(target_root), "target_roots": [str(target_root)]}
    ctl = s.Controller(cfg, FakePeer())
    ctl.ledger["stages"]["a" * 32] = {
        "state": "ready",
        "files": [{"relative": "raw.mkv", "source": str(original), "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}],
    }
    monkeypatch.setattr(s, "QB", lambda _cfg: target)
    monkeypatch.setattr("builtins.input", lambda _p: "RETURN")
    real = s.verify_pieces

    def proof(*a, **kw):
        events.append("proof")
        return real(*a, **kw)

    monkeypatch.setattr(s, "verify_pieces", proof)
    if unexpected_recheck:
        with pytest.raises(s.RefuseError, match='full recheck'):
            ctl.return_torrent(hash_)
        assert target.info_ is None
        assert 'source-registration-delete' not in events
        assert 'dedi-start' not in events
        assert original.read_bytes() == data
        assert ctl.ledger['returns'][hash_]['state'] == 'needs_review'
        assert ctl.ledger['returns'][hash_]['destination_recheck_refused'] is True
        return
    ctl.return_torrent(hash_)
    assert events.index("reannounce") < events.index("proof") < events.index("add") < events.index("source-registration-delete")
    assert original.read_bytes() == data and (target_root / "Uploads" / "renamed.mkv").samefile(original)
    assert ctl.ledger["returns"][hash_]["state"] == "returned"


def test_return_failure_restores_previously_running_source(tmp_path, monkeypatch):
    data = b"abcdefghijk"
    raw, hash_ = torrent(data)
    original = tmp_path / "original.mkv"
    original.write_bytes(data)
    target_root = tmp_path / "return"
    target_root.mkdir()
    events = []
    source = {
        "hash": hash_,
        "name": "Renamed title",
        "save_path": "/ssd/Uploads",
        "state": "uploading",
        "progress": 1,
        "amount_left": 0,
        "category": "",
        "tags": "test",
        "auto_tmm": False,
    }

    class FakeTarget:
        info_ = None

        def info(self, selected):
            assert selected == hash_
            return self.info_

        def call(self, path, args=None, **_kw):
            if path == "torrents/categories":
                return {}
            if path == "torrents/trackers":
                return []
            if path == "torrents/add":
                self.info_ = {**source, "save_path": args["savepath"], "state": "stoppedUP"}
                events.append("target-add")
                return b"Ok."
            raise AssertionError(path)

        def post(self, path, **_kw):
            events.append(path)

        def state(self, _hash, _start):
            events.append("target-start")
            self.info_["state"] = "uploading"

    class FakePeer:
        def qb(self, path, _args=None, **_kw):
            if path == "torrents/info":
                return [source]
            if path == "torrents/export":
                return raw
            if path == "torrents/files":
                return [{"name": "renamed.mkv", "size": len(data), "priority": 1}]
            if path == "torrents/trackers":
                return []
            if path == "torrents/reannounce":
                events.append("reannounce")
                return b""
            if path == "torrents/stop":
                events.append("source-stop")
                return b""
            if path == "torrents/delete":
                events.append("source-delete-failed")
                raise s.Refuse("injected source deletion failure")
            if path == "torrents/start":
                events.append("source-start-restore")
                return b""
            raise AssertionError(path)

        def rpc(self, action, **_kw):
            assert action == "inspect"
            return [{"path": "/ssd/Uploads/renamed.mkv", "size": len(data), "origin": ["c" * 32, "raw.mkv"], "inode": [1, 2]}]

    target = FakeTarget()
    cfg = {"state_dir": str(tmp_path / "state"), "return_root": str(target_root), "target_roots": [str(target_root)]}
    ctl = s.Controller(cfg, FakePeer())
    ctl.ledger["stages"]["c" * 32] = {
        "state": "ready",
        "files": [{"relative": "raw.mkv", "source": str(original), "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}],
    }
    monkeypatch.setattr(s, "QB", lambda _cfg: target)
    monkeypatch.setattr("builtins.input", lambda _p: "RETURN")
    with pytest.raises(s.Refuse, match="injected source deletion"):
        ctl.return_torrent(hash_)
    assert events.index("source-stop") < events.index("source-delete-failed") < events.index("source-start-restore")
    assert ctl.ledger["returns"][hash_]["state"] == "needs_review"
    assert (target_root / "renamed.mkv").samefile(original)


def test_cleanup_marks_exactly_verified_records_cleaned(tmp_path, monkeypatch):
    data = b"cleanup-proof"
    raw, hash_ = torrent(data, b"cleanup.bin")
    original = tmp_path / "cleanup.bin"
    original.write_bytes(data)
    payload = tmp_path / "returned"
    payload.mkdir()
    returned = payload / "cleanup.bin"
    returned.write_bytes(data)
    stage_id = "b" * 32
    info = {
        "hash": hash_,
        "save_path": str(payload),
        "progress": 1,
        "amount_left": 0,
        "state": "pausedUP",
    }

    class FakeTarget:
        def info(self, selected):
            assert selected == hash_
            return info

        def call(self, path, args=None, **kw):
            assert path == "torrents/export" and args == {"hash": hash_} and kw["binary"]
            return raw

    class FakePeer:
        def rpc(self, action, **fields):
            assert action == "clean"
            assert fields["stages"] == [stage_id]
            assert fields["links"][0]["inode"] == [7, 8]
            return {"removed_files": 2}

    cfg = {"state_dir": str(tmp_path / "state")}
    ctl = s.Controller(cfg, FakePeer())
    ctl.ledger["stages"][stage_id] = {"state": "ready", "files": []}
    ctl.ledger["returns"][hash_] = {
        "state": "returned",
        "origins": [{"path": "/ssd/Uploads/cleanup.bin", "inode": [7, 8], "origin": [stage_id, "cleanup.bin"]}],
    }
    monkeypatch.setattr(s, "QB", lambda _cfg: FakeTarget())
    monkeypatch.setattr("builtins.input", lambda _p: "CLEAN VERIFIED VPS COPIES")
    ctl.cleanup()
    assert ctl.ledger["returns"][hash_]["state"] == "cleaned"
    assert ctl.ledger["stages"][stage_id]["state"] == "cleaned"
    assert "cleaned_time" in ctl.ledger["returns"][hash_]
    assert original.read_bytes() == data
