"""Shared safe queue filters for paginated views and saved snapshots."""

from __future__ import annotations

import json
import re
import time

from src.catalogue_access import identity

SORTS = {
    "checked": "coalesce(checked,discovered) DESC,job_key",
    "title": "casefold(json_extract(candidate,'$.title')),job_key",
    "year_oldest": "cast(json_extract(candidate,'$.year') AS INTEGER),job_key",
    "votes_lowest": "cast(json_extract(candidate,'$.imdb_votes') AS INTEGER),job_key",
}


def extra_filters(db, value=None):
    value = {} if value is None else value
    if not isinstance(value, dict) or set(value) - {"year_min", "year_max", "min_votes", "language", "access", "sort"}:
        raise ValueError("Unsupported search filters")
    result = {"year_min": 0, "year_max": 0, "min_votes": 0, "language": "", "access": "", "sort": "checked", **value}
    for name, maximum in [("year_min", 2100), ("year_max", 2100), ("min_votes", 100000000)]:
        if type(result[name]) is not int or not 0 <= result[name] <= maximum:
            raise ValueError("Invalid year/vote filter")
    if result["year_min"] and result["year_max"] and result["year_min"] > result["year_max"]:
        raise ValueError("Earliest year exceeds latest year")
    if not isinstance(result["language"], str) or (result["language"] and not re.fullmatch("[a-z]{2}", result["language"])):
        raise ValueError("Use a two-letter original-language code")
    if result["access"] not in {"", "native_included", "manual_included", "rent_buy_or_addon", "unverified"} or result["sort"] not in SORTS:
        raise ValueError("Invalid access filter/order")
    clauses = []
    parameters = []
    for key, field, operator in [("year_min", "year", ">="), ("year_max", "year", "<="), ("min_votes", "imdb_votes", ">=")]:
        if result[key]:
            clauses.append(f"cast(json_extract(candidate,'$.{field}')AS INTEGER){operator}?")
            parameters.append(result[key])
    if result["language"]:
        clauses.append("json_extract(candidate,'$.original_language')=?")
        parameters.append(result["language"])
    if result["access"]:
        checks = []
        now = time.time()
        if db is not None:
            db.create_function("source_signature", 1, lambda raw: identity(json.loads(raw)), deterministic=True)
            for table, label, age in [("native_source_access", "native_included", 3600), ("source_access", "manual_included", 86400)]:
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                    checks.append(
                        f"(SELECT CASE decision WHEN 'included' THEN '{label}' WHEN 'paid' THEN 'rent_buy_or_addon' ELSE 'unverified' END FROM {table} a WHERE a.job_key=jobs.job_key AND a.signature=source_signature(jobs.candidate) AND a.checked BETWEEN ? AND ?)"  # noqa: S608 -- table/label are fixed internal constants above
                    )
                    parameters.extend([now - age, now])
        clauses.append("coalesce(" + ",".join([*checks, "'unverified'"]) + ")=?" if checks else "'unverified'=?")
        parameters.append(result["access"])
    return clauses, parameters, SORTS[result["sort"]], tuple(sorted(result.items()))
