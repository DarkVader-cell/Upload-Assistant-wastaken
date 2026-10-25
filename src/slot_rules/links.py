"""Public detail links from tracker-owned routes, never API/download credentials."""
from urllib.parse import parse_qsl, urlsplit


def public_detail_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        url = urlsplit(value)
        private_keys = {"passkey", "api_token", "apikey", "api_key", "token", "password", "authkey"}
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
            return None
        if any(k.casefold() in private_keys for k, _ in parse_qsl(url.query)):
            return None
        if any(part in url.path.casefold() for part in ("/download", "/api/")):
            return None
        return value
    except ValueError:
        return None


def linked_entry(entry: dict, tracker: str) -> dict:
    entry = dict(entry)
    for key in ("link", "details_url", "torrent_url", "permalink", "url"):
        link = public_detail_url(entry.get(key))
        if link:
            entry["link"] = link
            if urlsplit(link).path.rstrip("/").endswith("/torrents/pending"):
                entry["link_note"] = "Pending-queue listing: the tracker supplied no per-torrent permalink. Locate the displayed torrent ID in the queue."
            return entry
    entry.pop("link", None)
    id_ = entry.get("id") or entry.get("torrent_id") or entry.get("TorrentID")
    if not str(id_).isdigit() or int(id_) <= 0:
        return entry
    entry.setdefault("id", id_)
    # Import lazily to avoid the tracker setup -> slot rules import cycle.
    from src.trackersetup import tracker_class_map
    try:
        cls = tracker_class_map.get(tracker)
        prefix = getattr(cls, "torrent_url", "") if cls else ""
        if not prefix and tracker == "HDBITS":
            prefix = "https://hdbits.org/details.php?id="
        link = public_detail_url(str(prefix) + str(id_)) if prefix else None
        if link:
            entry["link"] = link
    except (ImportError, AttributeError, KeyError, TypeError):
        pass
    return entry
