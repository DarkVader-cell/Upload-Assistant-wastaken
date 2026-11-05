"""Run the dedicated-only browser smoke against isolated, API-disabled fixtures."""

import argparse
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.catalogue_runner import Store  # noqa: E402 -- standalone dedicated test bootstrap
from src.catalogue_web import atomic_json, password_record  # noqa: E402

SERVER = r"""
import sys
from pathlib import Path
from aiohttp import web
from src import catalogue_media_web as media

def fake_tmdb(self, path, parameters=None):
    if path == 'search/movie': return {'results':[{'id':42,'title':'Film','release_date':'2026-01-01','original_title':'Film'}]}
    if path == 'movie/42': return {'id':42,'title':'Film','release_date':'2026-01-01','imdb_id':'tt1234567','original_language':'en'}
    raise RuntimeError('Browser fixture forbids real metadata requests')
media.MediaUI.tmdb = fake_tmdb
media.planned_output = lambda *args, **kwargs: {'filename':'Film.2026.1080p.AMZN.WEB-DL.DDP5.1.H.264-Kitsune.mkv','folder':'','context':{}}
from src.catalogue_web import create_app, DASHBOARD_KEY
app = create_app(Path(sys.argv[1]), Path(sys.argv[2]))
async def forbidden_worker(*args):
    Path(sys.argv[3]).write_text('unexpected run request')
    raise RuntimeError('Browser fixture forbids all runner/API execution')
app[DASHBOARD_KEY].run_worker = forbidden_worker
app[DASHBOARD_KEY].media.execute = forbidden_worker
app[DASHBOARD_KEY].media.inspect = lambda body: {'writing_application':'CardinalDL fixture','output_application':'mkvmerge v74.0.0 fixture','container_title':'Original container title','tracks':[{'id':0,'type':'video','codec':'AVC','name':'Original video','language':'und','default':True,'forced':False,'hearing_impaired':False,'commentary':False},{'id':1,'type':'audio','codec':'E-AC-3','name':'Original audio','language':'en','default':True,'forced':False,'hearing_impaired':False,'commentary':False}],'tags':[{'name':'COMMENT','value':'synthetic private metadata','editable':True,'identity':False}],'attachments':[{'id':'1','name':'fixture-font.ttf','type':'font/ttf','size':128,'font':True}]}
async def fixture_health():
    return {'ok':True,'version':'3.10.16','message':'Synthetic fixture only; no CLI or service invocation'}
app[DASHBOARD_KEY].health = fixture_health
web.run_app(app, host='127.0.0.1', port=8781, access_log=None, print=None)
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser-python", type=Path, required=True)
    parser.add_argument("--browser-cache", type=Path, required=True)
    args = parser.parse_args()
    with socket.socket() as sock:
        if sock.connect_ex(("127.0.0.1", 8781)) == 0:
            raise SystemExit("Refusing occupied browser-test port")
    with tempfile.TemporaryDirectory(prefix="catalogue-browser-") as directory:
        temp = Path(directory)
        ua, config, auth = temp / "ua.py", temp / "runner.json", temp / "auth.json"
        marker, fake = temp / "unexpected-worker", temp / "fake-cardinal"
        state = temp / "state"
        state.mkdir(mode=0o700)
        ua.write_text("config={'TRACKERS':{'HDBITS':{'username':'fake','passkey':'fake'}}}")
        registry = temp / "ua-root/src/slot_rules/registry.py"
        registry.parent.mkdir(parents=True)
        registry.write_text("# Existence-only configuration fixture; never imported")
        fake.write_text("#!/bin/sh\nprintf '3.10.16\\n'\n")
        fake.chmod(0o700)
        media_root = temp / "media"
        media_root.mkdir(mode=0o700)
        (media_root / "Film.2026.1080p.AMZN.mkv").write_bytes(b"synthetic fixture, never processed")
        media_archive = temp / "media-release.pyz"
        media_archive.write_bytes(b"fixture download only")
        import hashlib

        atomic_json(temp / "VALIDATION.json", {"sha256": hashlib.sha256(media_archive.read_bytes()).hexdigest()})
        atomic_json(
            config,
            {
                "media_roots": [str(media_root)],
                "media_tool_archive": str(media_archive),
                "ua_config": str(ua),
                "state_dir": str(state),
                "cardinal_binary": str(fake),
                "cardinal_docker": {"container": "never-execute-browser-fixture"},
                "ua_root": str(temp / "ua-root"),
                "cardinal_exchange_host": str(temp / "exchange"),
                "cardinal_exchange_container": "/fixture-only",
                "services": {"netflix": {"region": "US"}},
                "trackers": ["HDB"],
                "origin_countries": ["IN"],
                "daily_limit": 2,
                "allow_downloads": False,
                "schedule": {"enabled": False, "mode": "plan", "interval_minutes": 60},
            },
        )
        atomic_json(auth, password_record("catalogue-browser-test"))
        store = Store(state / "queue.sqlite3")
        store.page("test", [{"imdb": "tt1234567", "service": "netflix", "region": "US", "item": "1", "title": "<img src=x onerror=alert(1)>"}], None)
        store.update("tt1234567", "unknown", "Synthetic fixture; recheck only")
        with store.db:
            for index in range(60):
                store.add(
                    {"imdb": f"tt{8000000 + index}", "service": "netflix", "region": "US", "item": str(index + 2), "title": f"Fixture {index:03}", "origin_countries": ["IN"]}
                )
        store.db.close()
        with (temp / "server.log").open("wb") as log:
            process = subprocess.Popen(  # noqa: S603 -- fixed API-disabled fixture server
                [sys.executable, "-c", SERVER, str(config), str(auth), str(marker)], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=log, start_new_session=True
            )
            try:
                # Dedicated-host contention can make cold Python imports slow.
                # Bound readiness independently of the browser's action timeout.
                ready_deadline = time.monotonic() + 90
                while time.monotonic() < ready_deadline:
                    if process.poll() is not None:
                        raise RuntimeError("Fixture server failed to start")
                    try:
                        with urlopen("http://127.0.0.1:8781/", timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(0.1)
                else:
                    raise RuntimeError("Fixture readiness timeout")
                result = subprocess.run(  # noqa: S603 -- fixed local browser test script
                    [str(args.browser_python), str(ROOT / "tests/catalogue_browser_smoke.py"), "http://127.0.0.1:8781/"],
                    env={**os.environ, "PLAYWRIGHT_BROWSERS_PATH": str(args.browser_cache)},
                    timeout=180,
                    check=False,
                )
                if result.returncode:
                    return result.returncode
                if marker.exists():
                    raise RuntimeError("Browser unexpectedly invoked the runner")
                return 0
            finally:
                process.terminate()
                try:
                    process.wait(timeout=35)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
