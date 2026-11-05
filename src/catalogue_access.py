"""Account-access review facts, separate from public catalogue availability.

Manual confirmation is explicitly labelled manual, expires, and cannot authorize
any download. Public FLATRATE data alone never proves Prime entitlement.
"""

from __future__ import annotations

import hashlib
import json
import time


def identity(candidate):
    return hashlib.sha256(json.dumps({key: candidate.get(key) for key in ("imdb", "service", "region", "item")}, sort_keys=True).encode()).hexdigest()


def access_state(db, candidate, key, now=None):
    now = time.time() if now is None else now
    native = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='native_source_access'").fetchone()
    if native:
        row = db.execute("SELECT signature,decision,checked FROM native_source_access WHERE job_key=?", (key,)).fetchone()
        if row and row[0] == identity(candidate) and 0 <= now - row[2] <= 3600:
            return {"included": "native_included", "paid": "rent_buy_or_addon", "unknown": "unverified"}.get(row[1], "unverified")
    table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='source_access'").fetchone()
    if not table:
        return "unverified"
    row = db.execute("SELECT signature,decision,checked FROM source_access WHERE job_key=?", (key,)).fetchone()
    now = time.time() if now is None else now
    if not row or row[0] != identity(candidate) or not 0 <= now - row[2] <= 86400:
        return "unverified"
    return {"included": "manual_included", "paid": "rent_buy_or_addon", "unknown": "unverified"}[row[1]]


def record_native_access(store, key, candidate, proof):
    decision = proof.get("state")
    if decision not in {"included", "paid", "unknown"}:
        raise ValueError("Invalid native account-access decision")
    with store.db:
        store.db.execute("CREATE TABLE IF NOT EXISTS native_source_access(job_key TEXT PRIMARY KEY,signature TEXT,decision TEXT,checked REAL)")
        store.db.execute("INSERT OR REPLACE INTO native_source_access VALUES(?,?,?,?)", (key, identity(candidate), decision, time.time()))


def record_access(store, key, decision):
    if decision not in {"included", "paid", "unknown"}:
        raise ValueError("Choose included, rent/buy/add-on, or unknown")
    row = store.db.execute("SELECT candidate,status,started_day FROM jobs WHERE job_key=?", (key,)).fetchone()
    if not row:
        raise ValueError("Title was not found")
    if row["started_day"] is not None or row["status"] in {"started", "succeeded", "failed", "uncertain"}:
        raise ValueError("Source review cannot replay an attempted download")
    candidate = json.loads(row["candidate"])
    with store.db:
        store.db.execute("CREATE TABLE IF NOT EXISTS source_access(job_key TEXT PRIMARY KEY,signature TEXT,decision TEXT,checked REAL)")
        store.db.execute("CREATE TABLE IF NOT EXISTS source_access_audit(job_key TEXT,signature TEXT,decision TEXT,checked REAL)")
        values = (key, identity(candidate), decision, time.time())
        store.db.execute("INSERT OR REPLACE INTO source_access VALUES(?,?,?,?)", values)
        store.db.execute("INSERT INTO source_access_audit VALUES(?,?,?,?)", values)
    # Optional notes are not entitlement proof and do not change queue status.
    # Only the automatic native check may qualify or exclude account access.
    return {"key": key, "source_access": access_state(store.db, candidate, key), "download_authorized": False, "expires_in_hours": 24}
