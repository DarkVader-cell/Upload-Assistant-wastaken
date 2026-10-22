#!/usr/bin/env python3
# Upload Assistant © 2026 Audionut & wastaken7 — Licensed under UAPL v1.0
"""SSH terminal raw-file staging and verified qBittorrent return.

No Dedi original is deleted. Paramiko is loaded only by the interactive peer.
The RPC worker uses the standard library, runs as the account owner, and accepts
only operations on the configured private staging workspace.
"""

import argparse
import ast
import base64
import contextlib
import curses
import fcntl
import getpass
import hashlib
import http.cookiejar
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path, PurePosixPath

CHUNK = 1024 * 1024
HASH = re.compile(r"^[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?$")


class RefuseError(RuntimeError):
    """A safety precondition was not satisfied; keep the source."""


Refuse = RefuseError


def require(test, message):
    if not test:
        raise Refuse(message)


def safe_relative(value):
    require(isinstance(value, str) and value and not any(ord(c) < 32 for c in value), "Invalid/control-character path")
    p = PurePosixPath(value)
    require(not p.is_absolute() and "\\" not in value and not re.match(r"^[A-Za-z]:", value), "Absolute/foreign path refused")
    require(all(x not in {"", ".", ".."} for x in value.split("/")), "Path traversal refused")
    return p


def confined(root, value):
    root = Path(root).resolve()
    path = Path(os.path.abspath(value))  # noqa: PTH100 -- retain lexical symlinks for the rejection below
    require(path.is_relative_to(root) and path != root, "Path is outside the permitted workspace")
    cursor = path
    while cursor != root:
        require(not cursor.is_symlink(), "Symlink path refused")
        cursor = cursor.parent
    return path


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name("." + path.name + "." + uuid.uuid4().hex)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(value, f)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def sha_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def fingerprint(path):
    s = Path(path).stat(follow_symlinks=False)
    require(stat.S_ISREG(s.st_mode), "Not a regular payload file")
    return [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns]


def manifest(source, roots):
    source = Path(os.path.abspath(source))  # noqa: PTH100 -- resolving first would hide an input symlink
    require(any(source.is_relative_to(Path(r).resolve()) for r in roots), "Select a configured media root, not arbitrary private/system files")
    require(not source.is_symlink(), "Symlink source refused")
    parent = source.parent
    entries = []
    todo = [source]
    while todo:
        p = todo.pop()
        require(len(entries) < 20000, "Too many files for this small staging workspace")
        confined(parent, p)
        mode = p.lstat().st_mode
        if stat.S_ISDIR(mode):
            todo.extend(p.iterdir())
        else:
            require(stat.S_ISREG(mode), "Symlinks and unusual filesystem objects are refused")
            rel = str(p.relative_to(parent))
            safe_relative(rel)
            entries.append({"relative": rel, "source": str(p), "fingerprint": fingerprint(p), "size": p.stat().st_size})
    require(entries, "The selection has no regular payload files")
    return entries


def torrent_files(raw, expected_hash=None, *, details=False):
    """Bounded bdecoder. Refuse unsupported v2/padding/renames rather than guess."""
    require(len(raw) <= 16 * CHUNK, "Torrent metadata is too large")
    pos = 0
    info_bytes = None

    def decode(depth=0):
        nonlocal pos, info_bytes
        require(depth < 40 and pos < len(raw), "Invalid torrent nesting")
        char = raw[pos : pos + 1]
        pos += 1
        if char == b"i":
            end = raw.index(b"e", pos)
            value = int(raw[pos:end])
            pos = end + 1
            return value
        if char in {b"l", b"d"}:
            value = [] if char == b"l" else {}
            while raw[pos : pos + 1] != b"e":
                item = decode(depth + 1)
                if isinstance(value, list):
                    value.append(item)
                else:
                    require(isinstance(item, bytes) and item not in value, "Invalid/duplicate torrent dictionary key")
                    start = pos
                    value[item] = decode(depth + 1)
                    if depth == 0 and item == b"info":
                        info_bytes = raw[start:pos]
                require(len(value) <= 40000, "Torrent has too many entries")
            pos += 1
            return value
        require(char.isdigit(), "Invalid bencoded torrent")
        end = raw.index(b":", pos - 1)
        length = int(raw[pos - 1 : end])
        pos = end + 1
        require(0 <= length <= len(raw) - pos, "Invalid torrent string length")
        value = raw[pos : pos + length]
        pos += length
        return value

    try:
        info = decode()[b"info"]
        require(pos == len(raw) and b"pieces" in info and b"meta version" not in info, "Only ordinary v1 UA torrents are currently supported")
        if expected_hash is not None:
            require(
                info_bytes is not None and hashlib.sha1(info_bytes, usedforsecurity=False).hexdigest() == expected_hash.lower(),
                "Exported torrent infohash differs from the selected source hash",
            )
        name = (info.get(b"name.utf-8") or info[b"name"]).decode("utf-8")
        safe_relative(name)
        require("/" not in name, "Invalid torrent root name")
        if b"files" not in info:
            result = [(name, int(info[b"length"]))]
        else:
            result = []
            for f in info[b"files"]:
                require(not f.get(b"attr") and b"symlink path" not in f, "Padding/symlink torrent layout needs manual handling")
                parts = f.get(b"path.utf-8") or f[b"path"]
                require(isinstance(parts, list) and parts, "Invalid torrent path")
                decoded = [x.decode("utf-8") for x in parts]
                require(all("/" not in x for x in decoded), "Invalid torrent path component")
                rel = "/".join([name, *decoded])
                safe_relative(rel)
                result.append((rel, int(f[b"length"])))
        require(result and all(n >= 0 for _, n in result), "Invalid torrent file size")
        require(len({p for p, _ in result}) == len(result), "Duplicate torrent file path")
        if details:
            length = info.get(b"piece length")
            pieces = info.get(b"pieces")
            require(isinstance(length, int) and 0 < length <= 64 * CHUNK and isinstance(pieces, bytes) and len(pieces) % 20 == 0, "Invalid torrent pieces")
            total = sum(size for _, size in result)
            require(total > 0 and (total + length - 1) // length == len(pieces) // 20, "Torrent piece count does not match payload")
            return result, length, pieces
        return result
    except Refuse:
        raise
    except (ValueError, KeyError, IndexError, TypeError, UnicodeError):
        raise Refuse("Unsupported or invalid torrent metadata") from None


def verify_pieces(raw, paths, expected_sha256=None):
    files, length, pieces = torrent_files(raw, details=True)
    require(len(paths) == len(files), "Incomplete verification file list")
    part = hashlib.sha1(usedforsecurity=False)
    used = 0
    index = 0
    for file_index, (path, (_, size)) in enumerate(zip(paths, files, strict=True)):
        before = fingerprint(path)
        h = hashlib.sha256()
        read = 0
        require(before[2] == size, "Dedi payload size mismatch")
        with Path(path).open("rb") as stream:
            for block in iter(lambda: stream.read(CHUNK), b""):
                h.update(block)
                read += len(block)
                start = 0
                while start < len(block):
                    n = min(length - used, len(block) - start)
                    part.update(block[start : start + n])
                    used += n
                    start += n
                    if used == length:
                        require(part.digest() == pieces[index * 20 : (index + 1) * 20], "Dedi torrent piece mismatch; VPS retained")
                        index += 1
                        used = 0
                        part = hashlib.sha1(usedforsecurity=False)
        require(read == size and fingerprint(path) == before, "Dedi file changed while verifying")
        if expected_sha256 is not None:
            require(h.hexdigest() == expected_sha256[file_index], "Dedi original differs from staged original")
    if used:
        require(part.digest() == pieces[index * 20 : (index + 1) * 20], "Final Dedi torrent piece mismatch; VPS retained")
        index += 1
    require(index == len(pieces) // 20, "Incomplete torrent piece verification")
    return True


class QB:
    def __init__(self, cfg):
        tree = ast.parse(Path(cfg["ua_config"]).read_text())
        assign = next(n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "config" for t in n.targets))
        client = ast.literal_eval(assign.value)["TORRENT_CLIENTS"][cfg["qbit_client"]]
        url = urllib.parse.urlsplit(client["qbit_url"])
        require(url.scheme in {"http", "https"} and bool(url.hostname), "qB endpoint must use HTTP(S)")
        netloc = url.netloc if url.port else url.netloc + ":" + str(client.get("qbit_port", 8080))
        self.base = urllib.parse.urlunsplit((url.scheme, netloc, url.path.rstrip("/"), "", ""))
        self.role = cfg["role"]
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.call("auth/login", {"username": client.get("qbit_user", ""), "password": client.get("qbit_pass", "")}, post=True, binary=True)

    def call(self, path, data=None, *, post=False, binary=False, torrent=None):
        data = dict(data or {})
        if path == "torrents/info" and self.role == "dedi":
            require(bool(HASH.fullmatch(str(data.get("hashes", "")))), "Unfiltered Dedi torrent inventory is forbidden")
        if "hashes" in data and path != "torrents/info":
            require(bool(HASH.fullmatch(str(data["hashes"]))), "Exactly one explicit torrent hash is required")
        if "hash" in data:
            require(bool(HASH.fullmatch(str(data["hash"]))), "Invalid torrent hash")
        if path == "torrents/delete":
            require(str(data.get("deleteFiles")).lower() == "false", "Deleting qB payload data through the API is forbidden")
        headers = {"Referer": self.base + "/"}
        body = None
        if torrent is not None:
            boundary = uuid.uuid4().hex
            chunks = []
            for key, value in data.items():
                chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
            chunks.extend(
                [
                    f'--{boundary}\r\nContent-Disposition: form-data; name="torrents"; filename="return.torrent"\r\nContent-Type: application/x-bittorrent\r\n\r\n'.encode(),
                    torrent,
                    f"\r\n--{boundary}--\r\n".encode(),
                ]
            )
            body = b"".join(chunks)
            headers["Content-Type"] = "multipart/form-data; boundary=" + boundary
        elif post:
            body = urllib.parse.urlencode(data).encode()
        url = self.base + "/api/v2/" + path
        if not post and data:
            url += "?" + urllib.parse.urlencode(data)
        try:
            with self.opener.open(urllib.request.Request(url, data=body, headers=headers), timeout=40) as response:  # noqa: S310 -- HTTP(S) scheme validated at construction
                raw = response.read(32 * CHUNK + 1)
            require(len(raw) <= 32 * CHUNK, "qB response exceeded safety bound")
            if binary:
                return raw
            return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            raise Refuse(f"qB request {path} failed (HTTP {e.code}); credentials/output suppressed") from None
        except (urllib.error.URLError, TimeoutError):
            raise Refuse(f"qB request {path} failed; source retained") from None

    def post(self, path, **data):
        return self.call(path, data, post=True, binary=True)

    def info(self, hash_):
        rows = self.call("torrents/info", {"hashes": hash_})
        require(len(rows) <= 1, "Unexpected hash lookup response")
        return rows[0] if rows else None

    def state(self, hash_, start):
        try:
            self.post("torrents/start" if start else "torrents/stop", hashes=hash_)
        except Refuse as e:
            if "404" not in str(e):
                raise
            self.post("torrents/resume" if start else "torrents/pause", hashes=hash_)


def qb_pages(qb):
    rows = []
    for offset in range(0, 20000, 200):
        page = qb.call("torrents/info", {"limit": 200, "offset": offset, "sort": "hash"})
        rows.extend(page)
        if len(page) < 200:
            return rows
    raise Refuse("VPS inventory exceeds safety limit; no cleanup performed")


def complete(info):
    return bool(
        info
        and float(info.get("progress", 0)) >= 1
        and int(info.get("amount_left", 1)) == 0
        and "check" not in info.get("state", "").lower()
        and "moving" not in info.get("state", "").lower()
        and info.get("state") not in {"missingFiles", "error"}
    )


def paused(info):
    return str(info.get("state", "")).startswith(("paused", "stopped"))


def rpc(cfg, request):
    action = request["action"]
    root = Path(cfg["stage_root"]).resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if action == "space":
        return {"free": shutil.disk_usage(root).free}
    if action == "prepare":
        id_ = request["id"]
        require(bool(re.fullmatch(r"[a-f0-9]{32}", id_)), "Invalid staging ID")
        directory = confined(root, root / "stages" / id_)
        require(not directory.exists(), "Staging ID already exists")
        (directory / "payload").mkdir(parents=True, mode=0o700)
        for item in request["files"]:
            (confined(root, directory / "payload" / safe_relative(item["relative"]))).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        return str(directory / "payload")
    if action == "commit":
        record = request["record"]
        directory = confined(root, root / "stages" / record["id"])
        for f in record["files"]:
            path = confined(root, directory / "payload" / safe_relative(f["relative"]))
            require(path.stat().st_size == f["size"] and sha_file(path) == f["sha256"], "SFTP copy checksum mismatch; staged data not approved")
        atomic_json(directory / "record.json", record)
        return True
    if action == "inspect":
        index = {}
        for ledger in (root / "stages").glob("*/record.json"):
            record = json.loads(ledger.read_text())
            for f in record["files"]:
                path = confined(root, ledger.parent / "payload" / safe_relative(f["relative"]))
                if path.is_file():
                    s = path.stat()
                    index[(s.st_dev, s.st_ino)] = [record["id"], f["relative"]]
        result = []
        for value in request["paths"]:
            path = confined(root, value)
            s = path.stat(follow_symlinks=False)
            require(stat.S_ISREG(s.st_mode), "Non-regular qB payload")
            require((s.st_dev, s.st_ino) in index, "VPS file has no proven raw-file staging origin; refuse name/size guesses")
            result.append({"path": str(path), "origin": index[(s.st_dev, s.st_ino)], "size": s.st_size, "inode": [s.st_dev, s.st_ino]})
        return result
    if action == "qb":
        require(
            request["path"]
            in {
                "torrents/info",
                "torrents/files",
                "torrents/export",
                "torrents/trackers",
                "torrents/reannounce",
                "torrents/start",
                "torrents/stop",
                "torrents/pause",
                "torrents/resume",
                "torrents/delete",
            },
            "Unsupported VPS qB action",
        )
        result = QB(cfg).call(request["path"], request.get("data"), post=request.get("post", False), binary=request.get("binary", False))
        return {"bytes": base64.b64encode(result).decode()} if isinstance(result, bytes) else result
    if action == "clean":
        # No automatic service stopping and no cleanup during UA sessions.
        for p in Path("/proc").glob("[0-9]*/cmdline"):
            with contextlib.suppress(OSError):
                require(b"upload.py" not in p.read_bytes(), "UA is running: cleanup deferred, source copies retained")
        qb = QB(cfg)
        rows = qb_pages(qb)
        refs = [Path(t["content_path"]) for t in rows if t.get("content_path")]

        def referenced(path):
            return any(path == r or path.is_relative_to(r) or r.is_relative_to(path) for r in refs)

        removed = 0
        for item in request["links"]:
            path = confined(root, item["path"])
            if not path.exists():
                continue
            s = path.stat(follow_symlinks=False)
            require([s.st_dev, s.st_ino] == item["inode"], "A returned link was replaced; keep it")
            require(not referenced(path), "A live VPS torrent still refers to this path")
            path.unlink()
            removed += 1
        for id_ in request["stages"]:
            directory = confined(root, root / "stages" / id_)
            ledger = directory / "record.json"
            if not ledger.is_file():
                continue
            record = json.loads(ledger.read_text())
            paths = []
            for f in record["files"]:
                path = confined(root, directory / "payload" / safe_relative(f["relative"]))
                if path.exists():
                    require(path.stat().st_nlink == 1 and not referenced(path), "Staged payload still has tracker hardlinks/references; cleanup deferred")
                    require(sha_file(path) == f["sha256"], "Staged payload changed since staging; keep it")
                    paths.append(path)
            for p in paths:
                p.unlink()
                removed += 1
            # Do not recursively remove unknown files or delete the audit record.
            for p in sorted((directory / "payload").rglob("*"), key=lambda x: len(x.parts), reverse=True):
                if p.is_dir():
                    with contextlib.suppress(OSError):
                        p.rmdir()
        return {"removed_files": removed}
    raise Refuse("Unknown worker action")


class Peer:
    def __init__(self, cfg):
        import paramiko

        self.cfg = cfg
        known_hosts = cfg.get("known_hosts")
        require(
            isinstance(known_hosts, str)
            and Path(known_hosts).is_file()
            and not Path(known_hosts).is_symlink(),
            "Pinned SSH known_hosts file is required",
        )
        self.ssh = paramiko.SSHClient()
        self.ssh.load_system_host_keys(filename=known_hosts)
        self.ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
        self.ssh.connect(
            cfg["remote"]["host"],
            port=cfg["remote"]["port"],
            username=cfg["remote"]["user"],
            password=None if cfg.get("ssh_key") else getpass.getpass("SSD VPS SSH password (not saved): "),
            key_filename=cfg.get("ssh_key"),
            look_for_keys=bool(cfg.get("ssh_key")),
            allow_agent=False,
            timeout=20,
        )
        self.sftp = paramiko.SFTPClient.from_transport(self.ssh.get_transport(), window_size=32 * CHUNK, max_packet_size=256 * 1024)

    def rpc(self, action, **fields):
        command = shlex.join(["python3", self.cfg["remote_script"], "--rpc"])
        stdin, stdout, _stderr = self.ssh.exec_command(command, timeout=3600)
        stdin.write(json.dumps({"action": action, **fields}))
        stdin.channel.shutdown_write()
        text = stdout.read(40 * CHUNK)
        require(stdout.channel.recv_exit_status() == 0, "Remote worker failed; raw output suppressed")
        answer = json.loads(text)
        require(answer.get("ok"), answer.get("error", "Remote action refused"))
        return answer["result"]

    def qb(self, path, data=None, *, post=False, binary=False):
        result = self.rpc("qb", path=path, data=data or {}, post=post, binary=binary)
        return base64.b64decode(result["bytes"]) if isinstance(result, dict) and "bytes" in result else result


class Controller:
    def __init__(self, cfg, peer):
        self.cfg, self.peer = cfg, peer
        self.directory = Path(cfg["state_dir"]).expanduser()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)
        self.lock = (self.directory / "lock").open("a")
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.path = self.directory / "ledger.json"
        self.ledger = json.loads(self.path.read_text()) if self.path.exists() else {"stages": {}, "returns": {}}

    def save(self):
        atomic_json(self.path, self.ledger)

    def stage(self, source):
        files = manifest(source, self.cfg["source_roots"])
        total = sum(f["size"] for f in files)
        free = self.peer.rpc("space")["free"]
        reserve = int(self.cfg.get("reserve_bytes", 8 * 1024**3))
        require(total <= free - reserve, "Insufficient SSD space after the safety reserve")
        id_ = uuid.uuid4().hex
        target = self.peer.rpc("prepare", id=id_, files=files)
        record = {"id": id_, "source": str(source), "remote_input": target + "/" + Path(source).name, "files": files, "state": "copying", "bytes_total": total, "bytes_sent": 0, "bytes_per_second": 0}
        transferred = 0
        transfer_started = time.monotonic()
        progress_saved = transfer_started
        self.ledger["stages"][id_] = record
        self.save()
        for f in files:
            require(fingerprint(f["source"]) == f["fingerprint"], "Source changed before SFTP")
            digest = hashlib.sha256()
            sent = 0
            started = time.monotonic()
            with Path(f["source"]).open("rb") as local, self.peer.sftp.open(target + "/" + f["relative"], "wb") as remote:
                remote.set_pipelined(True)
                for block in iter(lambda: local.read(CHUNK), b""):
                    remote.write(block)
                    digest.update(block)
                    sent += len(block)
                    transferred += len(block)
                    now = time.monotonic()
                    record.update(bytes_sent=transferred, bytes_per_second=transferred / max(0.01, now - transfer_started))
                    if now - progress_saved >= 1:
                        self.save()
                        progress_saved = now
                    print(
                        f"\rSFTP {Path(f['relative']).name}: {sent / CHUNK:.0f} MiB / {f['size'] / CHUNK:.0f} MiB  {sent / CHUNK / max(0.01, time.monotonic() - started):.1f} MiB/s",
                        end="",
                        flush=True,
                    )
            print()
            require(fingerprint(f["source"]) == f["fingerprint"], "Source changed during SFTP; copy not approved")
            f["sha256"] = digest.hexdigest()
            self.save()
        record["state"] = "verifying"
        self.save()
        self.peer.rpc("commit", record=record)
        record["state"] = "ready"
        self.save()
        print("Verified raw files ready on SSD. No original was deleted. Stage:", id_)

    def return_torrent(self, hash_, *, confirmed=False):
        require(bool(HASH.fullmatch(hash_)), "Invalid selected hash")
        rows = self.peer.qb("torrents/info", {"hashes": hash_})
        require(len(rows) == 1 and complete(rows[0]), "Select one completed VPS torrent")
        source = rows[0]
        require(hash_ not in self.ledger["returns"], "This hash already has a return record; inspect status before retrying")
        target = QB(self.cfg)
        require(target.info(hash_) is None, "Hash already exists on Dedi; no existing registration will be changed")
        raw = self.peer.qb("torrents/export", {"hash": hash_}, binary=True)
        wanted = torrent_files(raw, hash_)
        api_files = self.peer.qb("torrents/files", {"hash": hash_})
        require([(f["name"], int(f["size"])) for f in api_files] == wanted, "Renamed/unsupported file layout: refuse to guess paths")
        paths = [str(Path(source["save_path"]) / name) for name, _ in wanted]
        origins = self.peer.rpc("inspect", paths=paths)
        require(len(origins) == len(wanted), "Incomplete origin mapping")
        category = source.get("category", "")
        categories = target.call("torrents/categories")
        auto = bool(source.get("auto_tmm"))
        savepath = Path(self.cfg["return_root"])
        if category:
            safe_relative(category)
            if category in categories:
                if auto:
                    savepath = Path(categories[category].get("savePath") or target.call("app/preferences")["save_path"])
            else:
                savepath = savepath / category
        elif auto:
            savepath = Path(target.call("app/preferences")["save_path"])
        savepath = savepath.resolve()
        require(any(savepath.is_relative_to(Path(r).resolve()) for r in self.cfg["target_roots"]), "Category/default return path is outside approved media roots")
        plan = []
        for (name, size), origin in zip(wanted, origins, strict=True):
            id_, rel = origin["origin"]
            stage = self.ledger["stages"].get(id_)
            require(stage and stage["state"] == "ready", "No locally trusted ready staging record")
            f = next((f for f in stage["files"] if f["relative"] == rel), None)
            require(f and f["size"] == size and origin["size"] == size, "Payload origin/size mismatch")
            local = Path(f["source"])
            require(local.is_file() and not local.is_symlink(), "Dedi original missing; no deletion or guessed replacement")
            dest = confined(savepath, savepath / safe_relative(name))
            require(not dest.exists() or local.samefile(dest), "Destination collision; never overwrite existing files")
            plan.append((local, dest, f["sha256"]))
        print("Return:", source["name"], "\nCategory:", category or "(none)", "\nTags:", source.get("tags", ""), "\nDedi save path:", savepath)
        require(confirmed or input("Type RETURN to reannounce, link, import/recheck and transfer ONLY this torrent: ") == "RETURN", "Cancelled")
        initially_paused = paused(source)
        record = {"hash": hash_, "source": source, "save_path": str(savepath), "origins": origins, "state": "planned"}
        self.ledger["returns"][hash_] = record
        self.save()
        source_needs_restore = initially_paused
        try:
            if initially_paused:
                self.peer.qb("torrents/start", {"hashes": hash_}, post=True, binary=True)
            self.peer.qb("torrents/reannounce", {"hashes": hash_}, post=True, binary=True)
            record["reannounce_requested"] = time.time()
            self.save()
            print("VPS reannounce requested (not a claim of tracker acknowledgement).")
            print("Verifying exact torrent pieces against Dedi originals (no giant qB recheck queue)...")
            verify_pieces(raw, [p[0] for p in plan], [p[2] for p in plan])
            record["piece_proof_time"] = time.time()
            self.save()
            for local, dest, _sha in plan:
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not dest.exists():
                    os.link(local, dest)
            if category and category not in categories:
                target.post("torrents/createCategory", category=category, savePath=str(savepath))
            target.call(
                "torrents/add",
                {
                    "savepath": str(savepath),
                    "category": category,
                    "tags": source.get("tags", ""),
                    "paused": "true",
                    "stopped": "true",
                    "skip_checking": "true",
                    "autoTMM": "false",
                    "contentLayout": "Original",
                },
                post=True,
                binary=True,
                torrent=raw,
            )
            deadline = time.monotonic() + 60
            while target.info(hash_) is None and time.monotonic() < deadline:
                time.sleep(1)
            require(target.info(hash_) is not None, "Dedi did not import the exact source infohash")
            # Seed-mode import is allowed only after the independent full-piece
            # proof above, never based on filename, size, or cached progress.
            record["state"] = "checking"
            self.save()
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                info = target.info(hash_)
                if complete(info):
                    break
                if info and info.get("state") in {"missingFiles", "error"}:
                    raise Refuse("Dedi payload verification failed")
                print("\rDedi rechecking selected torrent; VPS source retained...", end="", flush=True)
                time.sleep(3)
            else:
                raise Refuse("Dedi verification timeout; source retained")
            print("\nExact Dedi torrent is complete.")
            info = target.info(hash_)
            require(Path(info["save_path"]).resolve() == savepath, "Dedi save path changed unexpectedly")
            target.post("torrents/setUploadLimit", hashes=hash_, limit=max(0, int(source.get("up_limit", 0))))
            target.post("torrents/setDownloadLimit", hashes=hash_, limit=max(0, int(source.get("dl_limit", 0))))
            target.post(
                "torrents/setShareLimits",
                hashes=hash_,
                ratioLimit=source.get("ratio_limit", -2),
                seedingTimeLimit=source.get("seeding_time_limit", -2),
                inactiveSeedingTimeLimit=source.get("inactive_seeding_time_limit", -2),
            )
            for key, endpoint in [("seq_dl", "toggleSequentialDownload"), ("f_l_piece_prio", "toggleFirstLastPiecePrio")]:
                if bool(source.get(key)) != bool(target.info(hash_).get(key)):
                    target.post("torrents/" + endpoint, hashes=hash_)
            for index, file in enumerate(api_files):
                target.post("torrents/filePrio", hash=hash_, id=index, priority=file.get("priority", 1))
            source_trackers = self.peer.qb("torrents/trackers", {"hash": hash_})
            target_trackers = target.call("torrents/trackers", {"hash": hash_})

            def tracker_set(rows):
                return {(r["url"], int(r.get("tier", 0))) for r in rows if str(r.get("url", "")).startswith(("http://", "https://", "udp://"))}

            require(tracker_set(source_trackers) == tracker_set(target_trackers), "Tracker URLs/tiers changed; source retained for manual review")
            target.post("torrents/setSuperSeeding", hashes=hash_, value=str(bool(source.get("super_seeding"))).lower())
            target.post("torrents/setAutoManagement", hashes=hash_, enable=str(auto).lower())
            target.post("torrents/rename", hash=hash_, name=source["name"])
            fresh = self.peer.qb("torrents/info", {"hashes": hash_})[0]
            require(fresh.get("category", "") == category and fresh.get("tags", "") == source.get("tags", ""), "VPS metadata changed during return; keep source")
            source_needs_restore = True
            self.peer.qb("torrents/stop", {"hashes": hash_}, post=True, binary=True)
            if not initially_paused:
                if source.get("force_start"):
                    target.post("torrents/setForceStart", hashes=hash_, value="true")
                else:
                    target.state(hash_, True)
            final = target.info(hash_)
            require(
                complete(final)
                and Path(final["save_path"]).resolve() == savepath
                and final.get("category", "") == category
                and {x.strip() for x in final.get("tags", "").split(",") if x.strip()} == {x.strip() for x in source.get("tags", "").split(",") if x.strip()},
                "Final Dedi verification/settings mismatch; keep VPS registration",
            )
            self.peer.qb("torrents/delete", {"hashes": hash_, "deleteFiles": "false"}, post=True, binary=True)
            source_needs_restore = False
            record["state"] = "returned"
            self.save()
            print("Returned and verified. VPS data retained until explicit verified cleanup. Local history counters are not transplanted.")
        except Exception:
            record["state"] = "needs_review"
            self.save()
            if source_needs_restore:
                with contextlib.suppress(Exception):
                    self.peer.qb(
                        "torrents/stop" if initially_paused else "torrents/start",
                        {"hashes": hash_},
                        post=True,
                        binary=True,
                    )
            raise

    def cleanup(self):
        qb = QB(self.cfg)
        links = []
        stages = set()
        for hash_, record in self.ledger["returns"].items():
            if record["state"] != "returned":
                continue
            info = qb.info(hash_)
            require(complete(info), "A returned Dedi torrent is no longer verified complete; no cleanup")
            raw = qb.call("torrents/export", {"hash": hash_}, binary=True)
            files = torrent_files(raw, hash_)
            paths = [confined(Path(info["save_path"]), Path(info["save_path"]) / safe_relative(name)) for name, _ in files]
            print("Re-verifying Dedi payload before deleting any SSD copies...")
            verify_pieces(raw, paths)
            links.extend(record["origins"])
            stages.update(x["origin"][0] for x in record["origins"])
        require(links, "No verified returns to clean")
        print("Only returned VPS tracker links and unreferenced, unchanged staged copies are eligible. Dedi originals are NEVER removed.")
        require(input("Type CLEAN VERIFIED VPS COPIES: ") == "CLEAN VERIFIED VPS COPIES", "Cancelled")
        result = self.peer.rpc("clean", links=links, stages=sorted(stages))
        cleaned_at = time.time()
        for record in self.ledger["returns"].values():
            if record["state"] == "returned":
                record["state"] = "cleaned"
                record["cleaned_time"] = cleaned_at
        for id_ in stages:
            stage = self.ledger["stages"].get(id_)
            if stage and stage["state"] == "ready":
                stage["state"] = "cleaned"
                stage["cleaned_time"] = cleaned_at
        self.save()
        print(result)


def choose(screen, title, labels, multiple=False):
    cursor = 0
    selected = set()
    while True:
        screen.erase()
        height, width = screen.getmaxyx()
        screen.addnstr(0, 0, title, max(1, width - 1), curses.A_BOLD)
        screen.addnstr(1, 0, "Arrows: navigate | Space: mark | Enter: accept | q: back", max(1, width - 1))
        offset = max(0, cursor - (height - 5))
        for i in range(offset, min(len(labels), offset + height - 3)):
            label = ("[x] " if i in selected else "[ ] ") if multiple else ""
            text = "".join(c if c.isprintable() else "?" for c in str(labels[i]))
            screen.addnstr(i - offset + 3, 0, label + text, max(1, width - 1), curses.A_REVERSE if i == cursor else 0)
        screen.refresh()
        key = screen.getch()
        if key in (ord("q"), 27):
            return []
        if key in (curses.KEY_DOWN, ord("j")) and labels:
            cursor = min(cursor + 1, len(labels) - 1)
        if key in (curses.KEY_UP, ord("k")):
            cursor = max(0, cursor - 1)
        if key == 32 and multiple and labels:
            if cursor in selected:
                selected.remove(cursor)
            else:
                selected.add(cursor)
        if key in (10, 13, curses.KEY_ENTER) and labels:
            return sorted(selected) if selected else [cursor]


def browse(screen, roots):
    current = None
    while True:
        if current is None:
            pick = choose(screen, "Choose a Dedi media root", roots)
            if not pick:
                return None
            current = Path(roots[pick[0]]).resolve()
        # Explicit directory selection avoids an unbounded recursive scan/API inventory.
        entries = []
        with os.scandir(current) as scan:
            for entry in scan:
                if not entry.name.startswith(".") and not entry.is_symlink():
                    entries.append(Path(entry.path))
                if len(entries) >= 1000:
                    break
        entries.sort(key=lambda p: (not p.is_dir(), p.name.casefold()))
        labels = ["Select this entire directory", "Parent / roots", *[("[DIR] " if p.is_dir() else "") + p.name for p in entries]]
        pick = choose(screen, "Raw files: " + str(current) + " (first 1000 entries)", labels)
        if not pick:
            return None
        i = pick[0]
        if i == 0:
            return current
        if i == 1:
            current = current.parent if any(current.parent.is_relative_to(Path(r).resolve()) for r in roots) else None
        elif entries[i - 2].is_dir():
            current = entries[i - 2]
        else:
            return entries[i - 2]


def tui(screen, controller):
    curses.curs_set(0)
    while True:
        pick = choose(
            screen,
            "HBD raw-file shuttle — originals stay on Dedi",
            [
                "Stage raw file/directory via SFTP",
                "Run UA on a verified staged item (SSH terminal)",
                "Return selected completed VPS torrents",
                "Clean verified SSD copies",
                "Status / recovery records",
                "Quit",
            ],
        )
        if not pick or pick[0] == 5:
            return
        action = pick[0]
        chosen = None
        if action == 0:
            chosen = browse(screen, controller.cfg["source_roots"])
            if chosen is None:
                continue
        elif action == 1:
            records = [r for r in controller.ledger["stages"].values() if r["state"] == "ready"]
            p = choose(screen, "Choose staged raw input for UA", [r["source"] for r in records])
            if not p:
                continue
            chosen = records[p[0]]
        elif action == 2:
            rows = controller.peer.qb("torrents/info", {"filter": "completed", "limit": 200, "offset": 0})
            p = choose(screen, "Completed SSD torrents (first 200; only staged origins accepted)", [f"{r['name']} | {r.get('category', '')}" for r in rows], True)
            if not p:
                continue
            chosen = [rows[i]["hash"] for i in p]
        curses.endwin()
        try:
            if action == 0:
                controller.stage(chosen)
            elif action == 1:
                remote = controller.cfg["remote"]
                command = shlex.join([*controller.cfg["remote_ua_command"], chosen["remote_input"]])
                subprocess.run(  # noqa: S603 -- fixed SSH executable and shlex-quoted remote argv
                    [
                        "/usr/bin/ssh",
                        "-tt",
                        "-p",
                        str(remote["port"]),
                        "-o",
                        "StrictHostKeyChecking=yes",
                        "-o",
                        "UserKnownHostsFile=" + controller.cfg["known_hosts"],
                        "-o",
                        "ConnectTimeout=20",
                        "-o",
                        "ServerAliveInterval=20",
                        "-o",
                        "ServerAliveCountMax=3",
                        remote["user"] + "@" + remote["host"],
                        command,
                    ],
                    check=True,
                )
            elif action == 2:
                for hash_ in chosen:
                    controller.return_torrent(hash_)
            elif action == 3:
                controller.cleanup()
            else:
                print(
                    json.dumps(
                        {
                            "ssd": controller.peer.rpc("space"),
                            "stages": {k: {"source": v["source"], "state": v["state"]} for k, v in controller.ledger["stages"].items()},
                            "returns": {k: v["state"] for k, v in controller.ledger["returns"].items()},
                        },
                        indent=2,
                    )
                )
        except (Refuse, OSError, ValueError, subprocess.SubprocessError) as e:
            print("Stopped safely:", e)
        input("\nPress Enter to return to the TUI...")
        screen.refresh()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(Path.home() / ".config/ua-hbd-shuttle/config.json"))
    parser.add_argument("--rpc", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--diagnose", action="store_true", help="Read-only path/API checks; never list all Dedi torrents")
    args = parser.parse_args()
    cfg = json.loads(Path(args.config).read_text())
    if args.rpc:
        try:
            print(json.dumps({"ok": True, "result": rpc(cfg, json.load(sys.stdin))}))
        except Exception as e:
            print(json.dumps({"ok": False, "error": str(e) if isinstance(e, Refuse) else type(e).__name__}))
        return
    if args.diagnose:
        qb = QB(cfg)
        print(
            json.dumps(
                {
                    "role": cfg["role"],
                    "qb_version": qb.call("app/version", binary=True).decode(),
                    "stage_root": cfg["stage_root"],
                    "ua_config_exists": Path(cfg["ua_config"]).is_file(),
                }
            )
        )
        return
    require(cfg["role"] == "dedi", "Run the interactive TUI on Dedi; the SSD hosts UA and the scoped worker")
    peer = Peer(cfg)
    controller = Controller(cfg, peer)
    try:
        curses.wrapper(tui, controller)
    finally:
        peer.sftp.close()
        peer.ssh.close()


if __name__ == "__main__":
    try:
        main()
    except (Refuse, KeyboardInterrupt, OSError) as e:
        print("Shuttle stopped:", str(e) or "cancelled", file=sys.stderr)
        raise SystemExit(1) from None
