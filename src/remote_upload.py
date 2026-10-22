"""Persistent remote-upload jobs using the provenance-verified shuttle engine.

Run on the payload-owning host: python -m src.remote_upload --help.
No tracker credentials are stored in the jobs database.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import shlex
import subprocess
import time
import uuid
from pathlib import Path
from types import SimpleNamespace


def load_engine():
    spec = importlib.util.spec_from_file_location("ua_shuttle", Path(__file__).resolve().parents[1] / "tools/hbd-shuttle.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Jobs:
    """Caller holds Controller's exclusive ledger lock for every operation."""

    def __init__(self, controller, engine, clock=time.time):
        self.controller, self.engine, self.clock = controller, engine, clock
        self.jobs = controller.ledger.setdefault("upload_jobs", {})

    def save(self):
        self.controller.save()

    def stage(self, source, delay):
        if not math.isfinite(delay) or delay < 0:
            raise ValueError("Return interval must be finite and nonnegative")
        before = set(self.controller.ledger["stages"])
        self.controller.stage(source)
        added = set(self.controller.ledger["stages"]) - before
        if len(added) != 1:
            raise ValueError("Ambiguous staging result")
        stage = self.controller.ledger["stages"][added.pop()]
        if stage["state"] != "ready":
            raise ValueError("Stage is not verified")
        id_ = uuid.uuid4().hex
        self.jobs[id_] = {"stage": stage["id"], "state": "staged", "delay": delay, "torrents": {}}
        self.save()
        return id_

    def run(self, id_, trackers, runner=subprocess.run, *, unattended=False):
        job = self.jobs[id_]
        if job["state"] != "staged":
            raise ValueError("Only staged jobs can run; ambiguous jobs require manual recovery")
        if not trackers or any(not t.replace("_", "").isalnum() for t in trackers):
            raise ValueError("Select explicit tracker identifiers")
        c = self.controller
        stage = c.ledger["stages"][job["stage"]]
        if stage["state"] != "ready":
            raise ValueError("Stage is no longer verified ready")
        inventory = SimpleNamespace(call=c.peer.qb)
        before = {r["hash"] for r in self.engine.qb_pages(inventory)}
        job.update(state="uploading", trackers=trackers)
        self.save()  # A crash must never automatically replay an upload POST.
        try:
            remote = c.cfg["remote"]
            command = shlex.join([*c.cfg["remote_ua_command"], stage["remote_input"], "-tk", ",".join(trackers), *(["--unattended"] if unattended else [])])
            argv = ["/usr/bin/ssh", "-T" if unattended else "-tt", "-p", str(remote["port"]), "-o", "StrictHostKeyChecking=yes", "-o", "UserKnownHostsFile=" + c.cfg["known_hosts"]]
            if c.cfg.get("ssh_key"):
                argv += ["-i", c.cfg["ssh_key"], "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes"]
            argv += ["-o", "ConnectTimeout=20", "-o", "ServerAliveInterval=20", "-o", "ServerAliveCountMax=3"]
            runner([*argv, remote["user"] + "@" + remote["host"], command], check=True)
            # Adopt only newly registered exact torrents whose EVERY payload
            # file maps to this job's independently verified staging manifest.
            for row in self.engine.qb_pages(inventory):
                hash_ = row["hash"]
                if hash_ in before:
                    continue
                files = c.peer.qb("torrents/files", {"hash": hash_})
                if not files:
                    continue
                paths = [str(Path(row["save_path"]) / self.engine.safe_relative(f["name"])) for f in files]
                try:
                    origins = c.peer.rpc("inspect", paths=paths)
                except self.engine.RefuseError:
                    continue
                if len(origins) == len(files) and all(o["origin"][0] == stage["id"] for o in origins):
                    job["torrents"][hash_] = {"state": "seeding", "due": self.clock() + job["delay"]}
            job["state"] = "seeding" if job["torrents"] else "needs_review"
            self.save()
        except Exception:
            job["state"] = "needs_review"
            self.save()
            raise

    def tick(self):
        """Return due jobs; never retry ambiguous handoffs or delete SSD data."""
        for job in self.jobs.values():
            if job["state"] != "seeding":
                continue
            for hash_, item in job["torrents"].items():
                if item["state"] != "seeding" or item["due"] > self.clock():
                    continue
                item["state"] = "returning"
                self.save()
                try:
                    self.controller.return_torrent(hash_, confirmed=True)
                    item["state"] = "returned"
                except Exception:
                    item["state"] = "needs_review"
                self.save()
            states = {i["state"] for i in job["torrents"].values()}
            if states == {"returned"}:
                job["state"] = "returned"
            elif "needs_review" in states or "returning" in states:
                job["state"] = "needs_review"
            self.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Private shuttle configuration for the selected remote backend")
    commands = parser.add_subparsers(dest="action", required=True)
    stage = commands.add_parser("stage")
    stage.add_argument("source", type=Path)
    stage.add_argument("--return-after", type=float, default=86400, help="Seconds of remote seeding after UA exits")
    run = commands.add_parser("upload")
    run.add_argument("job")
    run.add_argument("--trackers", nargs="+", required=True)
    execute = commands.add_parser("execute", help="Stage and upload as an unattended job (SSH key required)")
    execute.add_argument("source", type=Path)
    execute.add_argument("--return-after", type=float, default=86400)
    execute.add_argument("--trackers", nargs="+", required=True)
    commands.add_parser("tick", help="Return due registrations; suitable for a timer with SSH key authentication")
    commands.add_parser("status")
    args = parser.parse_args()
    engine = load_engine()
    cfg = json.loads(Path(args.config).expanduser().read_text())
    if args.action == "status":
        # Read status without connecting to the backend or prompting for SSH.
        ledger = Path(cfg["state_dir"]).expanduser() / "ledger.json"
        print(json.dumps(json.loads(ledger.read_text()).get("upload_jobs", {}) if ledger.exists() else {}, indent=2))
        return
    if cfg.get("role") != "dedi":
        raise ValueError("Run remote upload jobs on the payload-owning dedicated host")
    if args.action in {"execute", "tick"} and not cfg.get("ssh_key"):
        raise ValueError("Background operations require a configured SSH key")
    peer = engine.Peer(cfg)
    try:
        controller = engine.Controller(cfg, peer)
        jobs = Jobs(controller, engine)
        if args.action == "stage":
            print(jobs.stage(args.source, args.return_after))
        elif args.action == "upload":
            jobs.run(args.job, args.trackers)
        elif args.action == "execute":
            id_ = jobs.stage(args.source, args.return_after)
            jobs.run(id_, args.trackers, unattended=True)
        else:
            jobs.tick()
    finally:
        peer.sftp.close()
        peer.ssh.close()


if __name__ == "__main__":
    main()
