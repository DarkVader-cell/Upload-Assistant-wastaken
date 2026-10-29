"""Read-only capacity and exact-torrent evidence planning, never authorization."""
from __future__ import annotations

import hashlib
import json
import math

MAX_BYTES = 2 * 1024 * 1024
MAX_CANDIDATES = 500
FRESH_SECONDS = 3600


def _object(value, allowed, required=()):
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        raise ValueError('Unknown or missing snapshot fields')
    return value


def _label(value, limit=120):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError('Invalid label')
    return value.strip()


def _integer(value, nullable=False):
    if value is None and nullable:
        return None
    if type(value) is not int or not 0 <= value <= 2**63 - 1:
        raise ValueError('Invalid nonnegative byte count or link count')
    return value


def _time(value, now):
    if value is None:
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= now + 60:
        raise ValueError('Invalid evidence timestamp')
    return value


def _hash(value, lengths=(40, 64), nullable=False):
    if value is None and nullable:
        return None
    if not isinstance(value, str) or len(value) not in lengths or any(c not in '0123456789abcdefABCDEF' for c in value):
        raise ValueError('Invalid exact hash')
    return value.lower()


def _flag(value):
    if value is not None and type(value) is not bool:
        raise ValueError('Evidence flags must be boolean or null')
    return value


def validate_snapshot(snapshot, *, now):
    if len(json.dumps(snapshot, ensure_ascii=True)) > MAX_BYTES:
        raise ValueError('Snapshot too large')
    _object(snapshot, ('version', 'source', 'observed_at', 'destination', 'candidates'), ('version', 'source', 'destination', 'candidates'))
    if type(snapshot['version']) is not int or snapshot['version'] != 1:
        raise ValueError('Unsupported snapshot version')
    dest = _object(snapshot['destination'], ('id', 'role', 'capacity_bytes', 'used_bytes', 'pending_bytes', 'headroom_bytes', 'observed_at', 'estimated_bytes_per_second'), ('id', 'role'))
    if dest['role'] != 'grape':
        raise ValueError('This exact-torrent migration planner requires the Grape destination role')
    destination = {'id': _label(dest['id']), 'role': 'grape', 'observed_at': _time(dest.get('observed_at'), now)}
    for field in ('capacity_bytes', 'used_bytes', 'pending_bytes', 'headroom_bytes', 'estimated_bytes_per_second'):
        destination[field] = _integer(dest.get(field), nullable=True)
    if destination['estimated_bytes_per_second'] == 0:
        raise ValueError('Transfer estimate rate must be positive or unknown')
    if destination['capacity_bytes'] is not None and destination['used_bytes'] is not None and destination['used_bytes'] > destination['capacity_bytes']:
        raise ValueError('Used bytes exceed capacity')
    if not isinstance(snapshot['candidates'], list) or len(snapshot['candidates']) > MAX_CANDIDATES:
        raise ValueError('Maximum 500 candidates')
    candidates = []
    for raw in snapshot['candidates']:
        _object(raw, ('label', 'infohash', 'size_bytes', 'payload_sha256', 'origin_kind', 'state', 'source_identity_matches', 'age_gate_passed', 'lifecycle_gate_passed',
                      'tracker_hardlinks_remaining', 'tree', 'own_destination', 'related_handoffs', 'related_handoffs_complete', 'reuse'), ('label', 'infohash', 'size_bytes'))
        row = {'label': _label(raw['label']), 'infohash': _hash(raw['infohash']), 'size_bytes': _integer(raw['size_bytes']),
               'payload_sha256': _hash(raw.get('payload_sha256'), (64,), nullable=True)}
        for field, allowed in [('origin_kind', ('ua-original', 'direct-beyondhd', 'historical')), ('state', ('matched', 'recovery-required', 'unknown'))]:
            value = raw.get(field, 'unknown')
            if value not in (*allowed, 'unknown'):
                raise ValueError('Unknown source state')
            row[field] = value
        for field in ('source_identity_matches', 'age_gate_passed', 'lifecycle_gate_passed', 'related_handoffs_complete'):
            row[field] = _flag(raw.get(field))
        row['tracker_hardlinks_remaining'] = _integer(raw.get('tracker_hardlinks_remaining'), nullable=True)
        tree = _object(raw.get('tree', {}), ('kind', 'complete', 'observed_at', 'entries'))
        if tree.get('kind') not in (None, 'file', 'directory'):
            raise ValueError('Unknown tree kind')
        entries = tree.get('entries', [])
        if not isinstance(entries, list) or len(entries) > 5000:
            raise ValueError('Maximum 5000 tree entries')
        clean_entries = []
        for entry in entries:
            _object(entry, ('kind', 'nlink'), ('kind',))
            if entry['kind'] not in ('regular', 'symlink', 'other'):
                raise ValueError('Unknown tree object')
            clean_entries.append({'kind': entry['kind'], 'nlink': _integer(entry.get('nlink'), nullable=True)})
        row['tree'] = {'kind': tree.get('kind'), 'complete': _flag(tree.get('complete')), 'observed_at': _time(tree.get('observed_at'), now), 'entries': clean_entries}
        handoffs = raw.get('related_handoffs')
        if handoffs is not None and (not isinstance(handoffs, list) or len(handoffs) > 100):
            raise ValueError('Maximum 100 related handoffs')
        row['related_handoffs'] = None if handoffs is None else [_verification(v, now) for v in handoffs]
        row['own_destination'] = _verification(raw['own_destination'], now) if raw.get('own_destination') is not None else None
        reuse = raw.get('reuse')
        if reuse is not None:
            _object(reuse, ('destination_id', 'payload_sha256', 'size_bytes', 'verified', 'verified_at'), ('destination_id', 'size_bytes'))
            reuse = {'destination_id': _label(reuse['destination_id']), 'payload_sha256': _hash(reuse.get('payload_sha256'), (64,), nullable=True),
                     'size_bytes': _integer(reuse['size_bytes']), 'verified': _flag(reuse.get('verified')), 'verified_at': _time(reuse.get('verified_at'), now)}
        row['reuse'] = reuse
        candidates.append(row)
    return {'version': 1, 'source': _label(snapshot['source']), 'observed_at': _time(snapshot.get('observed_at'), now), 'destination': destination, 'candidates': candidates}


def _verification(value, now):
    _object(value, ('destination_id', 'infohash', 'complete', 'seed_ready', 'verified_at'), ('destination_id', 'infohash'))
    return {'destination_id': _label(value['destination_id']), 'infohash': _hash(value['infohash']), 'complete': _flag(value.get('complete')),
            'seed_ready': _flag(value.get('seed_ready')), 'verified_at': _time(value.get('verified_at'), now)}


def plan(snapshot, *, now):
    data = validate_snapshot(snapshot, now=now)
    dest = data['destination']
    def fresh(timestamp):
        return timestamp is not None and -60 <= now - timestamp <= FRESH_SECONDS

    def verified(evidence, infohash=None):
        return bool(evidence and evidence['destination_id'] == dest['id'] and (infohash is None or evidence['infohash'] == infohash)
                    and evidence['complete'] is True and evidence['seed_ready'] is True and fresh(evidence['verified_at']))
    global_blockers = []
    if not fresh(data['observed_at']):
        global_blockers.append('Snapshot is stale or undated')
    if not fresh(dest['observed_at']):
        global_blockers.append('Destination capacity evidence is stale or undated')
    fields = ('capacity_bytes', 'used_bytes', 'pending_bytes', 'headroom_bytes')
    if any(dest[f] is None for f in fields):
        global_blockers.append('Capacity, usage, pending bytes or required headroom is unknown')
    grouped, duplicate_count = {}, 0
    for row in data['candidates']:
        identity = row['infohash']
        if identity in grouped:
            duplicate_count += 1
            if grouped[identity]['record'] != row:
                grouped[identity]['conflicting'] = True
                grouped[identity]['record']['size_bytes'] = max(grouped[identity]['record']['size_bytes'], row['size_bytes'])
                grouped[identity]['record']['payload_sha256'] = None
        else:
            grouped[identity] = {'record': row, 'conflicting': False}
    rows, payloads = [], {}
    for item in grouped.values():
        row = item['record']
        blockers = list(global_blockers)
        if item['conflicting']:
            blockers.append('Conflicting duplicate exact-torrent records')
        if row['state'] != 'matched' or row['source_identity_matches'] is not True:
            blockers.append('Matching original handoff state and exact source identity are missing; historical sources require explicit recovery')
        if row['origin_kind'] == 'unknown':
            blockers.append('Source lifecycle kind is unknown')
        if row['age_gate_passed'] is not True:
            blockers.append('Source age gate is unverified')
        if row['origin_kind'] != 'direct-beyondhd' and row['lifecycle_gate_passed'] is not True:
            blockers.append('Upload lifecycle gate is unverified; retained to_upload tag alone is not a blocker')
        if not verified(row['own_destination'], row['infohash']):
            blockers.append('Original own exact infohash is not currently verified complete and seed-ready on Grape')
        if row['related_handoffs_complete'] is not True or row['related_handoffs'] is None or any(not verified(h) for h in row['related_handoffs']):
            blockers.append('All related tracker handoffs must be enumerated and verified on this destination')
        if row['tracker_hardlinks_remaining'] != 0:
            blockers.append('Tracker hardlinks remain or link state is unknown')
        tree = row['tree']
        if tree['complete'] is not True or not fresh(tree['observed_at']) or not tree['entries'] or tree['kind'] is None:
            blockers.append('Complete current inode/tree evidence is missing')
        if tree['kind'] == 'file' and len(tree['entries']) != 1:
            blockers.append('Single-file evidence must contain exactly one regular file')
        if any(e['kind'] != 'regular' for e in tree['entries']):
            blockers.append('Tree contains symlinks or unusual filesystem objects')
        if any(e['kind'] == 'regular' and e['nlink'] != 1 for e in tree['entries']):
            blockers.append('Every source regular file must have nlink == 1')
        reuse = row['reuse']
        safe_reuse = bool(reuse and row['payload_sha256'] and reuse['destination_id'] == dest['id'] and reuse['verified'] is True
                          and reuse['payload_sha256'] == row['payload_sha256'] and reuse['size_bytes'] == row['size_bytes'] and fresh(reuse['verified_at'])
                          and fresh(data['observed_at']) and fresh(dest['observed_at']) and not item['conflicting'])
        payload_key = (row['payload_sha256'], row['size_bytes']) if row['payload_sha256'] else ('torrent', row['infohash'])
        payload = payloads.setdefault(payload_key, {'size': row['size_bytes'], 'reuse': False})
        payload['reuse'] |= safe_reuse
        rows.append({'id': hashlib.sha256(row['infohash'].encode()).hexdigest(), 'label': row['label'], 'infohash': row['infohash'],
                     'size_bytes': row['size_bytes'], 'blockers': blockers, 'evidence_complete': not blockers,
                     'reuse': 'verified-snapshot-content-identity' if safe_reuse else 'candidate-only-unverified' if reuse else 'unknown',
                     'own_exact_torrent_verified': verified(row['own_destination'], row['infohash']), 'execution_authorized': False})
    transfer_bytes = sum(p['size'] for p in payloads.values() if not p['reuse'])
    reuse_bytes = sum(p['size'] for p in payloads.values() if p['reuse'])
    available = None if any(dest[f] is None for f in fields) else dest['capacity_bytes'] - dest['used_bytes'] - dest['pending_bytes'] - dest['headroom_bytes']
    shortage = None if available is None else max(0, transfer_bytes - available)
    if shortage:
        for row in rows:
            row['blockers'].append('Insufficient destination headroom for this selected batch')
            row['evidence_complete'] = False
    rate = dest['estimated_bytes_per_second']
    return {'version': 1, 'source': data['source'], 'observed_at': data['observed_at'], 'age_seconds': None if data['observed_at'] is None else max(0, now - data['observed_at']),
            'destination': dest, 'candidates': sorted(rows, key=lambda r: (not r['evidence_complete'], r['label'], r['infohash'])),
            'duplicate_candidates_ignored': duplicate_count, 'unique_payloads': len(payloads), 'additional_transfer_bytes': transfer_bytes,
            'verified_snapshot_reuse_bytes': reuse_bytes, 'available_after_reservations_bytes': available, 'shortage_bytes': shortage,
            'estimated_transfer_seconds': None if rate is None else transfer_bytes / rate, 'estimate_kind': 'operator-rate-heuristic-not-measurement',
            'execution_authorized': False, 'notice': 'Imported operator evidence, not live verification or execution authorization. No transfer, qB mutation or deletion is implemented. Unknown/stale/incomplete evidence blocks readiness.'}
