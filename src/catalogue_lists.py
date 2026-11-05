"""Durable, immutable discovery lists; never an execution/eligibility authority."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path

from aiohttp import web

from src.catalogue_state import SERVICES, STATUSES


def public_result(row, selected):
    candidate = json.loads(row["candidate"])
    evidence = json.loads(row["evidence"] or "null") or {}
    inventory = evidence.get("inventory", evidence if all(isinstance(v, str) for v in evidence.values()) else {})
    trackers = evidence.get("trackers", {})
    title_gap = bool(selected) and set(inventory) == set(selected) and all(v == "absent" for v in inventory.values())
    complete = (
        bool(selected)
        and set(trackers) == set(selected)
        and all(isinstance(v, dict) and v.get("state") in {"absent", "allow", "deny", "present", "not_applicable"} for v in trackers.values())
    )
    if complete:
        relevant = [v for v in trackers.values() if isinstance(v, dict) and v.get("state") != "not_applicable"]
        title_gap = bool(relevant) and all(v.get("state") == "absent" for v in relevant)
    slot_gap = complete and any(
        isinstance(v, dict) and (v.get("state") == "absent" or (v.get("state") == "allow" and v.get("requires_evidence") is False and v.get("trump") is False))
        for v in trackers.values()
    )
    return {
        **{key: candidate.get(key) for key in ("title", "year", "service", "region", "media_type", "season", "episode", "original_language")},
        "key": row["job_key"],
        "imdb": row["imdb"],
        "status": row["status"],
        "checked": row["checked"],
        "title_gap": title_gap,
        "slot_gap": slot_gap,
        "identity_verified": evidence.get("identity_verified") is True,
        "source_access": "unverified",
        "streaming_ready": False,  # Metadata/manifest availability is NOT subscription entitlement.
        "tracker_states": {
            alias: value if isinstance(value, str) else value.get("state", "unknown")
            for alias, value in (trackers or inventory).items()
            if alias in selected and isinstance(value, (str, dict))
        },
        "quality": {key: evidence.get("profile", {}).get(key) for key in ("resolution", "codec", "hdr", "audio_languages", "subtitle_languages")},
    }


class SavedLists:
    def __init__(self, reader, state):
        self.reader = reader
        self.root = Path(state) / "saved-lists"
        self.lock = threading.Lock()

    def connect(self):
        self.root.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        db = sqlite3.connect(self.root / "lists.sqlite3", timeout=5)
        db.row_factory = sqlite3.Row
        db.create_function("casefold", 1, lambda value: str(value or "").casefold(), deterministic=True)
        db.execute("CREATE TABLE IF NOT EXISTS lists(id TEXT PRIMARY KEY,title TEXT,created REAL,total INTEGER,filters TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS items(list_id TEXT,position INTEGER,data TEXT,PRIMARY KEY(list_id,position))")
        return db

    def save(self, body, selected, since=None):
        from src.catalogue_query import extra_filters

        extra_filters(None, body.get("filters"))
        title = body.get("title", "Discovery results")
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 120:
            raise ValueError("List title must be 1-120 characters")
        scope = body.get("scope", "gaps")
        status = body.get("status", "")
        service = body.get("service", "")
        query = body.get("q", "")
        if scope not in {"gaps", "all"} or (status and status not in STATUSES) or (service and service not in SERVICES) or not isinstance(query, str) or len(query) > 120:
            raise ValueError("Invalid saved-list filters")
        clauses = []
        parameters = []
        if status:
            clauses.append("status=?")
            parameters.append(status)
        if service:
            clauses.append("service=?")
            parameters.append(service)
        if query:
            clauses.append("(casefold(json_extract(candidate,'$.title')) LIKE ? ESCAPE '\\' OR imdb LIKE ? ESCAPE '\\')")
            escaped = query.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            parameters.extend([f"%{escaped}%", f"%{escaped}%"])
        if since is not None:
            clauses.append("checked>=?")
            parameters.append(since)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        identifier = secrets.token_hex(16)
        created = time.time()
        count = 0
        filters = {
            "scope": scope,
            "status": status,
            "service": service,
            "q": query,
            "extra": body.get("filters", {}),
            "selected_trackers": list(selected),
            "since": since,
            "streaming_access": "not proven; rent/buy never streaming-ready",
        }
        with self.lock, closing(self.connect()) as db, db:
            temporary = self.root / (identifier + ".partial")
            final = self.root / (identifier + ".json")
            try:
                with temporary.open("x", encoding="utf-8") as output:
                    temporary.chmod(0o600)
                    output.write('{"created":' + str(created) + ',"filters":' + json.dumps(filters) + ',"results":[')
                    if self.reader.path.exists():
                        source = self.reader._connect()
                        try:
                            source.execute("BEGIN")
                            from src.catalogue_query import extra_filters

                            extra, values, order, _key = extra_filters(source, body.get("filters"))
                            clauses.extend(extra)
                            parameters.extend(values)
                            where = " WHERE " + " AND ".join(clauses) if clauses else ""
                            rows = source.execute("SELECT job_key,imdb,candidate,evidence,status,checked FROM jobs" + where + " ORDER BY " + order, parameters)  # noqa: S608 -- fixed clauses; all client values are bound
                            while batch := rows.fetchmany(200):
                                for row in batch:
                                    item = public_result(row, selected)
                                    from src.catalogue_access import access_state

                                    item["source_access"] = access_state(source, json.loads(row["candidate"]), row["job_key"])
                                    if scope == "gaps" and item.get("service") == "amazon" and item["source_access"] != "native_included":
                                        continue
                                    if scope == "gaps" and not (item["title_gap"] or item["slot_gap"]):
                                        continue
                                    data = json.dumps(item, ensure_ascii=False)
                                    db.execute("INSERT INTO items VALUES(?,?,?)", (identifier, count, data))
                                    output.write(("," if count else "") + data)
                                    count += 1
                        finally:
                            source.close()
                    output.write('],"total":' + str(count) + "}")
                    output.flush()
                    os.fsync(output.fileno())
                temporary.replace(final)
                db.execute("INSERT INTO lists VALUES(?,?,?,?,?)", (identifier, title.strip(), created, count, json.dumps(filters)))
            except BaseException:
                temporary.unlink(missing_ok=True)
                final.unlink(missing_ok=True)
                raise
        return {"id": identifier, "title": title.strip(), "total": count, "created": created}

    def index(self, page=1):
        if type(page) is not int or not 1 <= page <= 1000000:
            raise ValueError("Invalid page")
        with closing(self.connect()) as db, db:
            total = db.execute("SELECT count(*) FROM lists").fetchone()[0]
            rows = db.execute("SELECT id,title,created,total,filters FROM lists ORDER BY created DESC,id LIMIT 25 OFFSET ?", ((page - 1) * 25,)).fetchall()
            return {"lists": [{**dict(row), "filters": json.loads(row["filters"])} for row in rows], "total": total, "page": page, "pages": max(1, (total + 24) // 25)}

    def page(self, identifier, page=1, size=50, query=""):
        if not isinstance(identifier, str) or len(identifier) != 32 or any(c not in "0123456789abcdef" for c in identifier):
            raise ValueError("Invalid list")
        if type(page) is not int or not 1 <= page <= 1000000 or type(size) is not int or size not in {25, 50, 100}:
            raise ValueError("Invalid pagination")
        if not isinstance(query, str) or len(query) > 120:
            raise ValueError("Search must be at most 120 characters")
        with closing(self.connect()) as db, db:
            metadata = db.execute("SELECT * FROM lists WHERE id=?", (identifier,)).fetchone()
            if metadata is None:
                raise web.HTTPNotFound(text="Saved list not found")
            total = metadata["total"]
            if query:
                escaped = query.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                where = "list_id=? AND (casefold(json_extract(data,'$.title')) LIKE ? ESCAPE '\\' OR json_extract(data,'$.imdb') LIKE ? ESCAPE '\\')"
                parameters = (identifier, f"%{escaped}%", f"%{escaped}%")
                total = db.execute("SELECT count(*) FROM items WHERE " + where, parameters).fetchone()[0]  # noqa: S608 -- static clauses, bound parameters
                rows = db.execute("SELECT data,position FROM items WHERE " + where + " ORDER BY position LIMIT ? OFFSET ?", (*parameters, size, (page - 1) * size)).fetchall()  # noqa: S608
            else:
                rows = db.execute("SELECT data,position FROM items WHERE list_id=? AND position>=? ORDER BY position LIMIT ?", (identifier, (page - 1) * size, size)).fetchall()
            has_review = db.execute("SELECT 1 FROM sqlite_master WHERE type='table'AND name='manual_review'").fetchone()

            def result(row):
                review = db.execute("SELECT state,note,updated FROM manual_review WHERE list_id=?AND position=?", (identifier, row[1])).fetchone() if has_review else None
                return {
                    **json.loads(row[0]),
                    "position": row[1],
                    "manual_review": {"state": review[0] if review else "new", "note": review[1] if review else "", "updated": review[2] if review else None},
                }

            return {
                **dict(metadata),
                "total": total,
                "list_total": metadata["total"],
                "filters": json.loads(metadata["filters"]),
                "results": [result(row) for row in rows],
                "page": page,
                "page_size": size,
                "pages": max(1, (total + size - 1) // size),
            }


def install_list_routes(app, dashboard, object_body):
    lists = SavedLists(dashboard.reader, dashboard.config()["state_dir"])
    dashboard.saved_lists = lists

    async def index(request):
        return web.json_response(await asyncio.to_thread(lists.index, int(request.query.get("page", "1"))))

    async def save(request):
        body = await object_body(request)
        if dashboard.busy:
            raise web.HTTPConflict(text="Wait for the scan to finish before saving its results")
        return web.json_response(await asyncio.to_thread(lists.save, body, dashboard.config().get("trackers", [])))

    async def page(request):
        return web.json_response(
            await asyncio.to_thread(
                lists.page, request.match_info["identifier"], int(request.query.get("page", "1")), int(request.query.get("page_size", "50")), request.query.get("q", "")
            )
        )

    async def export(request):
        identifier = request.match_info["identifier"]
        await asyncio.to_thread(lists.page, identifier, 1, 25)
        return web.FileResponse(
            lists.root / (identifier + ".json"), headers={"Content-Disposition": f'attachment; filename="catalogue-list-{identifier}.json"', "Content-Type": "application/json"}
        )

    app.router.add_get("/api/lists", index)
    app.router.add_post("/api/lists", save)
    app.router.add_get("/api/lists/{identifier:[a-f0-9]{32}}", page)
    app.router.add_get("/api/lists/{identifier:[a-f0-9]{32}}/export", export)
    return lists
