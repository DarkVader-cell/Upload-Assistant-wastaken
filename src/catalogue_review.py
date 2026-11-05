"""Manual-upload review notes and safe named search presets; no upload actions."""

from __future__ import annotations

import asyncio
import json
import secrets
import time
from contextlib import closing

from aiohttp import web

FILTER_KEYS = frozenset(
    {
        "services",
        "trackers",
        "origin_countries",
        "original_languages",
        "media_types",
        "eligibility",
        "include_specials",
        "selection_order",
        "min_release_year",
        "max_release_year",
        "min_imdb_votes",
        "max_imdb_votes",
        "min_runtime_minutes",
        "max_runtime_minutes",
        "exclude_title_keywords",
        "video_mode",
        "max_checks_per_run",
        "pages_per_service",
        "discovery_start_offset",
    }
)


class Review:
    def __init__(self, lists, dashboard):
        self.lists, self.dashboard = lists, dashboard

    def connect(self):
        db = self.lists.connect()
        db.execute("CREATE TABLE IF NOT EXISTS manual_review(list_id TEXT,position INTEGER,state TEXT,note TEXT,updated REAL,PRIMARY KEY(list_id,position))")
        db.execute("CREATE TABLE IF NOT EXISTS search_presets(id TEXT PRIMARY KEY,name TEXT,settings TEXT,updated REAL)")
        return db

    def mark(self, identifier, body):
        self.lists.page(identifier, 1, 25)
        positions = body.get("positions")
        state = body.get("state")
        note = body.get("note", "")
        if not isinstance(positions, list) or not 1 <= len(positions) <= 100 or any(type(p) is not int or p < 0 for p in positions) or len(set(positions)) != len(positions):
            raise ValueError("Select 1-100 unique list rows")
        if state not in {"keep", "skip", "uploaded", "new"} or not isinstance(note, str) or len(note) > 500:
            raise ValueError("Invalid manual review state/note")
        with closing(self.connect()) as db, db:
            for position in positions:
                if not db.execute("SELECT 1 FROM items WHERE list_id=? AND position=?", (identifier, position)).fetchone():
                    raise ValueError("Selected row does not exist")
            for position in positions:
                db.execute("INSERT OR REPLACE INTO manual_review VALUES(?,?,?,?,?)", (identifier, position, state, note, time.time()))
        return {"saved": len(positions), "state": state, "manual_only": True, "tracker_or_upload_actions": False}

    def presets(self, body=None):
        with closing(self.connect()) as db, db:
            if body is None:
                return {
                    "presets": [
                        {"id": r[0], "name": r[1], "settings": json.loads(r[2]), "updated": r[3]}
                        for r in db.execute("SELECT * FROM search_presets ORDER BY updated DESC,id LIMIT 50")
                    ]
                }
            if "delete" in body:
                identifier = body["delete"]
                if not isinstance(identifier, str) or len(identifier) != 32 or any(c not in "0123456789abcdef" for c in identifier):
                    raise ValueError("Invalid preset")
                db.execute("DELETE FROM search_presets WHERE id=?", (identifier,))
                return {"deleted": True, "configuration_changed": False}
            name = body.get("name")
            settings = body.get("settings")
            if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100 or not isinstance(settings, dict) or set(settings) - FILTER_KEYS:
                raise ValueError("Preset may contain only search filters and batch sizes")
            from src.catalogue_runner import load_settings

            if "services" in settings:
                services = settings["services"]
                if (
                    not isinstance(services, dict)
                    or set(services) - {"amazon", "netflix", "appletv"}
                    or any(not isinstance(value, dict) or set(value) - {"region", "daily_limit"} for value in services.values())
                ):
                    raise ValueError("Presets may store service regions/limits, not profiles or credentials")
            from src.catalogue_web import atomic_json

            path = self.lists.root / ("preset-validation-" + secrets.token_hex(12) + ".json")
            try:
                atomic_json(path, {**self.dashboard.config(), **settings})
                load_settings(path)
            finally:
                path.unlink(missing_ok=True)
            existing = db.execute("SELECT id FROM search_presets WHERE lower(name)=lower(?)", (name.strip(),)).fetchone()
            if not existing and db.execute("SELECT count(*)FROM search_presets").fetchone()[0] >= 50:
                raise ValueError("Maximum 50 named presets")
            identifier = existing[0] if existing else secrets.token_hex(16)
            db.execute("INSERT OR REPLACE INTO search_presets VALUES(?,?,?,?)", (identifier, name.strip(), json.dumps(settings), time.time()))
            return {"id": identifier, "name": name.strip(), "saved": True, "applied": False}

    def export(self, identifier):
        self.lists.page(identifier, 1, 25)
        target = self.lists.root / (identifier + ".review.json")
        temp = self.lists.root / (identifier + "." + secrets.token_hex(8) + ".partial")
        try:
            with closing(self.connect()) as db, db, temp.open("x", encoding="utf-8") as output:
                temp.chmod(0o600)
                db.execute("BEGIN")
                metadata = dict(db.execute("SELECT * FROM lists WHERE id=?", (identifier,)).fetchone())
                output.write('{"list":' + json.dumps(metadata) + ',"manual_review_only":true,"results":[')
                first = True
                rows = db.execute(
                    "SELECT i.data,i.position,r.state,r.note,r.updated FROM items i LEFT JOIN manual_review r ON r.list_id=i.list_id AND r.position=i.position WHERE i.list_id=? ORDER BY i.position",
                    (identifier,),
                )
                while batch := rows.fetchmany(200):
                    for row in batch:
                        item = {**json.loads(row[0]), "position": row[1], "manual_review": {"state": row[2] or "new", "note": row[3] or "", "updated": row[4]}}
                        output.write(("" if first else ",") + json.dumps(item, ensure_ascii=False))
                        first = False
                output.write("]}")
            temp.replace(target)
        finally:
            temp.unlink(missing_ok=True)
        return target


def install_review_routes(app, dashboard, lists, object_body):
    review = Review(lists, dashboard)

    async def presets(request):
        body = await object_body(request) if request.method == "POST" else None
        return web.json_response(await asyncio.to_thread(review.presets, body))

    async def mark(request):
        return web.json_response(await asyncio.to_thread(review.mark, request.match_info["identifier"], await object_body(request)))

    async def export(request):
        path = await asyncio.to_thread(review.export, request.match_info["identifier"])
        return web.FileResponse(
            path, headers={"Content-Disposition": f'attachment; filename="manual-upload-review-{request.match_info["identifier"]}.json"', "Content-Type": "application/json"}
        )

    async def source(request):
        body = await object_body(request)
        if dashboard.busy:
            raise web.HTTPConflict(text="Wait for the current scan before reviewing source access")

        def save_source():
            from src.catalogue_access import record_access
            from src.catalogue_runner import Store, locked_state

            with locked_state(dashboard.reader.path.parent):
                store = Store(dashboard.reader.path)
                try:
                    row = store.db.execute("SELECT candidate FROM jobs WHERE job_key=?", (body.get("key"),)).fetchone()
                    if not row:
                        raise ValueError("Title not found")
                    candidate = json.loads(row[0])
                    if body.get("region") != candidate.get("region"):
                        raise ValueError("Confirm the displayed account region; do not assume another country")
                    if body.get("decision") == "included" and body.get("checked_in_account") is not True:
                        raise ValueError("Confirm you checked existing subscription access, not rent/buy or an extra channel")
                    return record_access(store, body.get("key"), body.get("decision"))
                finally:
                    store.db.close()

        return web.json_response(await asyncio.to_thread(save_source))

    app.router.add_get("/api/presets", presets)
    app.router.add_post("/api/presets", presets)
    app.router.add_post("/api/lists/{identifier:[a-f0-9]{32}}/review", mark)
    app.router.add_get("/api/lists/{identifier:[a-f0-9]{32}}/review-export", export)
    app.router.add_post("/api/source-review", source)
    return review
