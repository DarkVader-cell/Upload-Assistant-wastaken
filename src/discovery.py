"""Bounded recorded-evidence discovery. Local absence is never tracker absence."""
from __future__ import annotations

import hashlib
import math
import os
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

MAX_RECORDS = 5000
FIELDS = ('category', 'resolution', 'codec', 'language', 'edition')
STALE_SECONDS = 7 * 86400


def approved_path(value: object, roots: Iterable[Path]) -> Path:
    if not isinstance(value, str) or not value or '\x00' in value or not Path(value).is_absolute():
        raise ValueError('Invalid absolute source path')
    path = Path(value).resolve()
    if not any(path != root and path.is_relative_to(root) for root in roots):
        raise ValueError('Source outside approved library roots')
    return path


def candidates(records: Iterable[Mapping[str, Any]], roots: Iterable[str | Path], *, now: float) -> tuple[list[dict[str, Any]], bool]:
    """Normalize at most 5000 projections, without scanning directories or clients."""
    roots = tuple(Path(root).resolve() for root in roots)
    grouped: dict[str, dict[str, Any]] = {}
    truncated = False
    for number, record in enumerate(records):
        if number >= MAX_RECORDS:
            truncated = True
            break
        try:
            path = approved_path(record.get('source_path', record.get('path')), roots)
        except (ValueError, OSError, RuntimeError):
            continue
        key = os.path.normcase(str(path))
        row = grouped.setdefault(key, {'id': hashlib.sha256(key.encode()).hexdigest(), 'source_path': str(path),
                                     'release_name': path.name, 'evidence': [], 'values': {f: set() for f in FIELDS},
                                     'successful_trackers': set(), 'failed_trackers': set(), 'trackers': set()})
        timestamp = record.get('updated_at')
        timestamp = timestamp if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool) and math.isfinite(timestamp) and 0 < timestamp <= now else None
        row['evidence'].append({'source': 'history' if record.get('origin') == 'history' else 'browse-index',
                                'observed_at': timestamp, 'stale': timestamp is None or now - timestamp > STALE_SECONDS})
        for field in FIELDS:
            value = record.get(field)
            if isinstance(value, str) and value.strip():
                row['values'][field].add(value.strip()[:200])
        for field in ('successful_trackers', 'failed_trackers', 'trackers'):
            values: list[Any] = record.get(field, [])
            if isinstance(values, list):
                row[field].update(v for v in values if isinstance(v, str) and len(v) <= 80)
    result: list[dict[str, Any]] = []
    for row in grouped.values():
        blockers = ['Tracker absence, capabilities, slot availability and seed status are unknown']
        for field, values in row.pop('values').items():
            row[field] = next(iter(values)) if len(values) == 1 else None
            if len(values) > 1:
                blockers.append(f'Conflicting recorded {field}')
        try:
            exists = Path(row['source_path']).exists()
        except OSError:
            exists = False
        if not exists:
            blockers.append('Source missing')
        fresh = any(not e['stale'] for e in row['evidence'])
        if not fresh:
            blockers.append('Recorded evidence stale or undated')
        row['failed_trackers'] -= row['successful_trackers']
        for field in ('successful_trackers', 'failed_trackers', 'trackers'):
            row[field] = sorted(row[field])
        missing = sum(row[f] is None for f in FIELDS)
        row.update(blockers=blockers, preparation_ready=exists and fresh and not any(b.startswith('Conflicting') for b in blockers),
                   estimated_work={'kind': 'heuristic-units-not-time', 'value': missing + (2 if not row['successful_trackers'] else 0)},
                   ranking_reasons=['Available source and fresh unambiguous evidence first', 'Lower missing-metadata preparation estimate next',
                                    'Prior recorded successes before failures; path breaks ties'])
        result.append(row)
    return result, truncated


def select(rows: Iterable[dict[str, Any]], *, trackers: Iterable[str] = (), mode: str = 'missing', query: str = '',
           filters: dict[str, str] | None = None, offset: int = 0, limit: int = 100) -> dict[str, Any]:
    if mode not in ('missing', 'failed', 'unattempted') or type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError('Invalid discovery filters')
    filters = filters or {}
    if set(filters) - set(FIELDS) or len(query) > 200:
        raise ValueError('Invalid metadata filters')
    selected = set(trackers)
    result: list[dict[str, Any]] = []
    for row in rows:
        target = {'missing': selected - set(row['successful_trackers']), 'failed': selected & set(row['failed_trackers']),
                  'unattempted': selected - set(row['trackers'])}[mode]
        if selected and not target:
            continue
        if query.casefold() not in (row['release_name'] + ' ' + row['source_path']).casefold():
            continue
        if any(value and (row.get(field) or '').casefold() != value.casefold() for field, value in filters.items()):
            continue
        result.append({**row, 'proposed_trackers': sorted(target)})
    result.sort(key=lambda r: (not r['preparation_ready'], r['estimated_work']['value'], -len(r['successful_trackers']), len(r['failed_trackers']), r['source_path']))
    return {'rows': result[offset:offset + limit], 'total': len(result), 'offset': offset, 'limit': limit}


def preview(rows: Iterable[dict[str, Any]], ids: list[str], targets: Iterable[str], validate_path: Callable[[str], str]) -> dict[str, Any]:
    if not isinstance(ids, list) or not 1 <= len(ids) <= 50 or any(not isinstance(i, str) for i in ids):
        raise ValueError('Select 1-50 candidates')
    by_id = {r['id']: r for r in rows}
    plans: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for identity in dict.fromkeys(ids):
        row = by_id.get(identity)
        if row is None:
            raise ValueError('Unknown candidate; refresh discovery')
        pending = sorted(set(targets) - set(row['successful_trackers']))
        if not pending:
            skipped.append({'id': identity, 'reason': 'Already recorded successful'})
            continue
        try:
            path = str(validate_path(row['source_path']))
        except (ValueError, OSError):
            skipped.append({'id': identity, 'reason': 'Source missing, ambiguous or outside approved roots'})
            continue
        plans.append({'id': identity, 'path': path, 'label': row['release_name'], 'trackers': pending,
                      'blockers': row['blockers'], 'requires_confirmation': True})
    return {'plans': plans, 'skipped': skipped, 'notice': 'Preparation only. Normal tracker verification and screenshot approval still apply.'}
