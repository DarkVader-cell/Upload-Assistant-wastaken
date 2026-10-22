"""Release-centric projection of recorded upload attempts; never claims site absence."""
import hashlib


def releases(store):
    grouped = {}
    for offset in range(0, store.max_entries, 500):
        rows = store.search(limit=500, offset=offset)
        for row in rows:
            path = row.get('source_path', '')
            if not path:
                continue
            id_ = hashlib.sha256(path.encode()).hexdigest()
            item = grouped.setdefault(id_, {**row, 'id': id_, 'attempts': 0, 'successful_trackers': set(), 'failed_trackers': set(), 'trackers': set()})
            item['attempts'] += 1
            for key in ('successful_trackers', 'failed_trackers', 'trackers'):
                item[key].update(row.get(key, []))
        if len(rows) < 500:
            break
    for item in grouped.values():
        item['failed_trackers'] -= item['successful_trackers']
        for key in ('successful_trackers', 'failed_trackers', 'trackers'):
            item[key] = sorted(item[key])
        item.pop('tracker_uploads', None)
    return list(grouped.values())


def filter_releases(rows, *, query='', trackers=(), mode='missing', category='', resolution='', errors=False):
    selected = set(trackers)
    result = []
    for row in rows:
        success, attempted, failed = (set(row[k]) for k in ('successful_trackers', 'trackers', 'failed_trackers'))
        targets = {'missing': selected - success, 'uploaded': selected & success, 'failed': selected & failed, 'unattempted': selected - attempted}
        if mode not in targets:
            raise ValueError('Unknown tracker filter')
        if selected and not targets[mode]:
            continue
        if query.casefold() not in (row.get('release_name', '') + ' ' + row['source_path']).casefold():
            continue
        if category and row.get('category') != category:
            continue
        if resolution and row.get('resolution') != resolution:
            continue
        if errors and not failed and row.get('status') != 'failed':
            continue
        result.append(row)
    return result
