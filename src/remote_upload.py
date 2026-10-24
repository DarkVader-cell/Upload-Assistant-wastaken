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

from src.remote_transfer_control import process_start


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

    def reuse_stage(self, stage_id, source, delay):
        if not math.isfinite(delay) or delay < 0:
            raise ValueError("Invalid return interval")
        stage = self.controller.ledger["stages"].get(stage_id)
        if not stage or stage.get("state") != "ready" or Path(stage["source"]).resolve() != Path(source).resolve():
            raise ValueError("No ready staged copy matches this exact source")
        if not stage.get("writer_start") or process_start(stage.get("writer_pid")) == stage["writer_start"]:
            raise ValueError("Staging writer identity is unavailable or still active")
        if any(self.engine.fingerprint(f["source"]) != f["fingerprint"] for f in stage["files"]):
            raise ValueError("Original changed since staging; existing copy cannot be reused automatically")
        paths = [str(Path(stage["remote_input"]).parent / f["relative"]) for f in stage["files"]]
        origins = self.controller.peer.rpc("inspect", paths=paths)
        if len(origins) != len(stage["files"]) or any(o.get("origin") != [stage_id, f["relative"]] or o.get("size") != f["size"] for o, f in zip(origins, stage["files"], strict=True)):
            raise ValueError("Existing VPS copy has no matching staged provenance")
        # Keep the prior needs_review job intact. Explicit reuse creates a new
        # attempt and still runs every ordinary UA duplicate/policy check.
        id_ = uuid.uuid4().hex
        self.jobs[id_] = {"stage": stage_id, "state": "staged", "delay": delay, "torrents": {}, "reused": True}
        self.save()
        return id_

    def run(self, id_, trackers, runner=subprocess.run, *, unattended=False, arguments=(), webui=False):
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
        job.update(state="uploading", trackers=trackers, arguments=list(arguments))
        self.save()  # A crash must never automatically replay an upload POST.
        try:
            remote = c.cfg["remote"]
            ui_env = ["env", "PYTHONUNBUFFERED=1", "UA_WEBUI_FORCE_COLOR=1", "UA_WEBUI_PROGRESS_STDOUT=1", "UA_WEBUI_PROMPT_SOUND_STDOUT=1", "UA_STATS_SOURCE=webui"] if webui else []
            command = shlex.join([*ui_env, *c.cfg["remote_ua_command"], stage["remote_input"], *arguments, "-tk", ",".join(trackers), *(["--unattended"] if unattended else [])])
            argv = ["/usr/bin/ssh", "-T" if unattended or webui else "-tt", "-p", str(remote["port"]), "-o", "StrictHostKeyChecking=yes", "-o", "UserKnownHostsFile=" + c.cfg["known_hosts"]]
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
        except BaseException:
            job["state"] = "needs_review"
            self.save()
            raise

    def tick(self):
        """Return due jobs; optionally clean only fully verified, closed batches."""
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
        self.sync_cleaned_jobs()
        if getattr(self.controller, "cfg", {}).get("auto_cleanup_verified") is True:
            for job in self.jobs.values():
                if job["state"] != "returned" or job.get("cleanup_retry_at", 0) > self.clock():
                    continue
                job["cleanup_status"] = "checking"
                self.save()
                try:
                    result = self.controller.cleanup(confirmed=True, stage_ids=[job["stage"]])
                    job["cleanup_result"] = result
                    self.sync_cleaned_jobs()
                except Exception as error:
                    job["cleanup_status"] = "blocked"
                    refusal = getattr(self.engine, "RefuseError", None)
                    job["cleanup_error"] = str(error) if refusal is not None and isinstance(error, refusal) else type(error).__name__
                    job["cleanup_retry_at"] = self.clock() + 300
                self.save()

    def sync_cleaned_jobs(self):
        for job in self.jobs.values():
            if job["state"] != "returned" or self.controller.ledger["stages"].get(job.get("stage"), {}).get("state") != "cleaned":
                continue
            if not all(self.controller.ledger.get("returns", {}).get(h, {}).get("state") == "cleaned" for h in job["torrents"]):
                continue
            for item in job["torrents"].values():
                item["state"] = "cleaned"
            job.update(state="cleaned", cleanup_status="cleaned", cleaned_at=self.clock())
            job.pop("cleanup_error", None)
            job.pop("cleanup_retry_at", None)
        self.save()


def webui_entry(argv):
    """Run under the EXISTING WebUI process/session pump, inheriting stdin/stdout."""
    from web_ui.remote_upload import backends, remote_options

    source = Path(argv[0]).resolve(strict=True)
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--remote-backend", required=True)
    parser.add_argument("--remote-return-after", type=float, default=86400)
    parser.add_argument("--remote-stage")
    parser.add_argument("-tk", "--trackers", required=True)
    args, remaining = parser.parse_known_args(argv[1:])
    config = backends().get(args.remote_backend)
    if config is None:
        raise ValueError("Unknown remote backend")
    cfg = json.loads(config.read_text())
    if cfg.get("role") != "dedi" or not cfg.get("ssh_key"):
        raise ValueError("Remote WebUI needs a dedicated backend with SSH-key authentication")
    if not any(source.is_relative_to(Path(root).resolve()) and source != Path(root).resolve() for root in cfg["source_roots"]):
        raise ValueError("Release is outside backend source roots")
    options = remote_options(shlex.join(remaining))
    trackers = args.trackers.split(",")
    if not trackers or any(not t.replace("_", "").isalnum() for t in trackers):
        raise ValueError("Invalid explicit tracker selection")
    engine = load_engine()
    peer = engine.Peer(cfg)
    try:
        controller = engine.Controller(cfg, peer)
        jobs = Jobs(controller, engine)
        id_ = jobs.reuse_stage(args.remote_stage, source, args.remote_return_after) if args.remote_stage else jobs.stage(source, args.remote_return_after)
        print("Staging ready. Starting interactive remote UA in this terminal.", flush=True)
        jobs.run(id_, trackers, arguments=options, webui=True)
    finally:
        peer.sftp.close()
        peer.ssh.close()


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
    execute.add_argument("--arguments-json", default="[]")
    discard = commands.add_parser("discard", help="Remove only a stopped stage's verified unreferenced partial files")
    discard.add_argument("stage")
    cleanup = commands.add_parser("cleanup", help="Explicit verified cleanup of selected returned stages")
    cleanup.add_argument("--stage", action="append", required=True)
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
    if args.action in {"execute", "tick", "discard", "cleanup"} and not cfg.get("ssh_key"):
        raise ValueError("Background operations require a configured SSH key")
    peer = engine.Peer(cfg)
    try:
        controller = engine.Controller(cfg, peer)
        jobs = Jobs(controller, engine)
        if args.action == "stage":
            print(jobs.stage(args.source, args.return_after))
        elif args.action == "upload":
            jobs.run(args.job, args.trackers)
        elif args.action == "cleanup":
            controller.cleanup(confirmed=True, stage_ids=args.stage)
            jobs.sync_cleaned_jobs()
        elif args.action == "discard":
            print(controller.discard_partial(args.stage))
        elif args.action == "execute":
            id_ = jobs.stage(args.source, args.return_after)
            jobs.run(id_, args.trackers, unattended=True, arguments=json.loads(args.arguments_json))
        else:
            jobs.tick()
    finally:
        peer.sftp.close()
        peer.ssh.close()


if __name__ == "__main__":
    main()
