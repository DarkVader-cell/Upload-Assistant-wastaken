"""Versioned declarative suggestions. This module cannot execute or submit anything."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, cast

FIELDS = ('category', 'resolution', 'codec', 'language', 'edition', 'media_type')
OPERATORS = ('equals', 'in', 'contains')
REQUIREMENTS = ('metadata-review', 'screenshot-review', 'torrent-verification')
ACTIONS = ('suggest_trackers', 'preset', 'client_profile', 'requirements')
MAX_BYTES = 256 * 1024


def _keys(value: dict[str, Any], required: tuple[str, ...]) -> None:
    if not isinstance(value, dict) or set(value) != set(required):
        raise ValueError('Unknown or missing schema fields')


def _text(value: object, maximum: int = 200) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise ValueError('Invalid text value')
    return value.strip()


def validate_actions(actions: dict[str, Any], references: dict[str, list[str]]) -> dict[str, Any]:
    if not isinstance(actions, dict) or not actions or set(actions) - set(ACTIONS):
        raise ValueError('Unknown or empty action')
    result: dict[str, Any] = {}
    for key, value in actions.items():
        allowed = set(REQUIREMENTS if key == 'requirements' else references.get(key, ()))
        if key in ('suggest_trackers', 'requirements'):
            if not isinstance(value, list) or not 1 <= len(value) <= 100:
                raise ValueError('Invalid action list')
            values = [_text(v, 80) for v in cast(list[Any], value)]
            if set(values) - allowed or len(values) != len(set(values)):
                raise ValueError('Unknown or repeated action reference')
            result[key] = sorted(values)
        else:
            value = _text(value, 80)
            if value not in allowed:
                raise ValueError('Unknown preset or client profile')
            result[key] = value
    return result


def validate_schema(schema: dict[str, Any], references: dict[str, list[str]]) -> dict[str, Any]:
    """Strict limits, literal operators only, and validated existing profile names."""
    if len(json.dumps(schema, ensure_ascii=True)) > MAX_BYTES:
        raise ValueError('Schema too large')
    _keys(schema, ('version', 'rules', 'overrides'))
    if type(schema['version']) is not int or schema['version'] != 1:
        raise ValueError('Unsupported rule version')
    if not isinstance(schema['rules'], list) or len(schema['rules']) > 32:
        raise ValueError('Maximum 32 rules')
    rules: list[dict[str, Any]] = []
    names: set[str] = set()
    input_rules = cast(list[dict[str, Any]], schema['rules'])
    for rule in input_rules:
        _keys(rule, ('name', 'priority', 'enabled', 'match', 'conditions', 'actions'))
        name = _text(rule['name'], 80)
        if name.casefold() in names:
            raise ValueError('Rule names must be unique')
        names.add(name.casefold())
        if type(rule['priority']) is not int or not -1000 <= rule['priority'] <= 1000 or type(rule['enabled']) is not bool or rule['match'] not in ('all', 'any'):
            raise ValueError('Invalid rule flags or priority')
        if not isinstance(rule['conditions'], list) or not 1 <= len(rule['conditions']) <= 32:
            raise ValueError('Select 1-32 conditions')
        conditions: list[dict[str, Any]] = []
        input_conditions = cast(list[dict[str, Any]], rule['conditions'])
        for condition in input_conditions:
            _keys(condition, ('field', 'operator', 'value'))
            field, operator, value = condition['field'], condition['operator'], condition['value']
            if field not in FIELDS or operator not in OPERATORS:
                raise ValueError('Unknown condition field or operator')
            if operator == 'in':
                if not isinstance(value, list) or not 1 <= len(value) <= 32:
                    raise ValueError('Invalid condition list')
                value = [_text(v) for v in cast(list[Any], value)]
            else:
                value = _text(value)
            conditions.append({'field': field, 'operator': operator, 'value': value})
        rules.append({'name': name, 'priority': rule['priority'], 'enabled': rule['enabled'], 'match': rule['match'],
                      'conditions': conditions, 'actions': validate_actions(rule['actions'], references)})
    overrides: dict[str, dict[str, Any]] = schema['overrides']
    if not isinstance(overrides, dict) or len(overrides) > 500:
        raise ValueError('Maximum 500 overrides')
    clean_overrides: dict[str, dict[str, Any]] = {}
    for identity, actions in overrides.items():
        if not isinstance(identity, str) or len(identity) != 64 or any(c not in '0123456789abcdef' for c in identity):
            raise ValueError('Overrides require a candidate identity')
        clean_overrides[identity] = validate_actions(actions, references)
    return {'version': 1, 'rules': rules, 'overrides': clean_overrides}


def evaluate(schema: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """Deterministic priority winners; lists union, scalar conflicts are explained."""
    proposals: dict[str, Any] = {'requirements': ['screenshot-review', 'torrent-verification']}
    provenance: dict[str, list[str]] = {'requirements': ['mandatory-safety-floor']}
    explanations: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for rule in sorted(schema['rules'], key=lambda r: (-r['priority'], r['name'].casefold())):
        conditions: list[dict[str, Any]] = []
        for condition in rule['conditions']:
            actual = candidate.get(condition['field'])
            known = isinstance(actual, str) and bool(actual.strip())
            expected = condition['value']
            value = actual.strip().casefold() if isinstance(actual, str) else ''
            matched = known and (value in [v.casefold() for v in expected] if condition['operator'] == 'in' else
                                 expected.casefold() in value if condition['operator'] == 'contains' else value == expected.casefold())
            conditions.append({**condition, 'actual': actual if known else None, 'known': known, 'matched': bool(matched),
                               'provenance': 'recorded-candidate-metadata' if known else 'unknown'})
        matched = rule['enabled'] and (all(c['matched'] for c in conditions) if rule['match'] == 'all' else any(c['matched'] for c in conditions))
        explanations.append({'rule': rule['name'], 'enabled': rule['enabled'], 'priority': rule['priority'], 'match': rule['match'],
                             'matched': matched, 'conditions': conditions})
        if matched:
            for action, value in rule['actions'].items():
                if action in ('requirements', 'suggest_trackers'):
                    proposals[action] = sorted(set(proposals.get(action, [])) | set(value))
                    provenance.setdefault(action, []).append(rule['name'])
                elif action not in proposals:
                    proposals[action] = value
                    provenance[action] = [rule['name']]
                elif proposals[action] != value:
                    conflicts.append({'action': action, 'winner': proposals[action], 'ignored': value, 'rule': rule['name'], 'reason': 'higher-priority-or-name-tiebreak'})
    override = schema['overrides'].get(candidate['id'], {})
    for action, value in override.items():
        if action == 'requirements':
            proposals[action] = sorted(set(proposals[action]) | set(value))
        else:
            if action in proposals and proposals[action] != value:
                conflicts.append({'action': action, 'winner': value, 'ignored': proposals[action], 'reason': 'explicit-per-release-override'})
            proposals[action] = value
        provenance[action] = ['explicit-per-release-override']
    return {'candidate_id': candidate['id'], 'proposals': proposals, 'provenance': provenance, 'rules': explanations, 'conflicts': conflicts,
            'requires_confirmation': True, 'notice': 'Suggestions only. Verification, edition/slot safety, screenshot approval and submission confirmation cannot be disabled.'}


class RuleStore:
    """Atomic state persistence with optimistic revisions; never writes config.py."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.lock = threading.Lock()

    def _load(self, references: dict[str, list[str]]) -> tuple[dict[str, Any], str]:
        if not self.path.exists():
            schema: dict[str, Any] = {'version': 1, 'rules': [], 'overrides': {}}
        else:
            if self.path.is_symlink() or self.path.stat().st_size > MAX_BYTES:
                raise ValueError('Invalid rule state')
            schema = validate_schema(json.loads(self.path.read_text()), references)
        revision = hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest()
        return schema, revision

    def load(self, references: dict[str, list[str]]) -> tuple[dict[str, Any], str]:
        with self.lock:
            return self._load(references)

    def save(self, schema: dict[str, Any], revision: str, references: dict[str, list[str]]) -> tuple[dict[str, Any], str]:
        clean = validate_schema(schema, references)
        with self.lock:
            _, current = self._load(references)
            if revision != current:
                raise FileExistsError('Rules changed; reload before saving')
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix='.automation-rules-', dir=self.path.parent)
            temporary = Path(name)
            try:
                with os.fdopen(fd, 'w') as stream:
                    json.dump(clean, stream, indent=2)
                    stream.flush()
                    os.fsync(stream.fileno())
                temporary.replace(self.path)
            finally:
                temporary.unlink(missing_ok=True)
            return self._load(references)
