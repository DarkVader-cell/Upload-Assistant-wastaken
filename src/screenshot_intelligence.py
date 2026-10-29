"""Small local image signals, not OCR or artistic quality judgements."""
from __future__ import annotations

import hashlib
import io
import json
import threading
import time
import warnings
from collections import OrderedDict
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, TypedDict

import numpy as np
from PIL import Image, ImageOps

from src.screenshot_review import ReviewedScreenshot


class Score(TypedDict):
    version: str
    brightness: float
    black_fraction: float
    detail: float
    edge_proxy: float
    reasons: list[str]
    fingerprint: int
    thumbnail: bytes


MAX_IMAGES = 100
MAX_PIXELS = 16_000_000
MAX_BYTES = 16 * 1024 * 1024
ALGORITHM_VERSION = 1


class ImageAnalyzer:
    """Serialized decode + bounded identity/version LRU, with no network access."""

    def __init__(self, cache_size: int = 256) -> None:
        self._cache: OrderedDict[tuple[object, ...], Score] = OrderedDict()
        self._lock = threading.Lock()
        self.cache_size = max(1, min(256, cache_size))
        self.decodes = 0

    def inspect(self, path: str | Path, root: str | Path, version: int = 0, cancelled: Callable[[], bool] = lambda: False) -> Score:
        path, root = Path(path), Path(root).resolve()
        resolved = path.resolve()
        if path.is_symlink() or not resolved.is_relative_to(root) or resolved == root or not resolved.is_file():
            raise ValueError('Image outside execution workspace')
        stat = resolved.stat()
        if stat.st_size > MAX_BYTES:
            raise ValueError('Image byte limit exceeded')
        key = (str(resolved), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, version, ALGORITHM_VERSION)
        with self._lock:
            if cancelled():
                raise InterruptedError('Analysis cancelled')
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(resolved) as image:
                    if image.width * image.height > MAX_PIXELS or image.width < 8 or image.height < 8 or max(image.size) / min(image.size) > 100 or getattr(image, 'n_frames', 1) != 1:
                        raise ValueError('Unsupported image dimensions or animation')
                    image = ImageOps.exif_transpose(image)
                    image.thumbnail((192, 108))
                    gray_image = image.convert('L').resize((max(2, image.width), max(2, image.height)))
                    gray = np.asarray(gray_image, dtype=np.float32) / 255
                    brightness = float(gray.mean())
                    black_fraction = float((gray < 0.04).mean())
                    detail = float(gray.std())
                    edge = float((np.abs(np.diff(gray, axis=0)).mean() + np.abs(np.diff(gray, axis=1)).mean()) / 2)
                    hash_image = np.asarray(image.convert('L').resize((9, 8)), dtype=np.int16)
                    bits = hash_image[:, 1:] > hash_image[:, :-1]
                    fingerprint = int.from_bytes(np.packbits(bits).tobytes(), 'big')
                    output = io.BytesIO()
                    image.convert('RGB').save(output, format='JPEG', quality=75)
            if cancelled():
                raise InterruptedError('Analysis cancelled')
            reasons: list[str] = []
            if brightness < 0.06 and black_fraction > 0.9:
                reasons.append('near-black')
            if detail < 0.05 or edge < 0.008:
                reasons.append('low-detail-or-blur-proxy')
            identity = hashlib.sha256(repr(key).encode()).hexdigest()
            result: Score = {'version': identity, 'brightness': round(brightness, 4), 'black_fraction': round(black_fraction, 4),
                      'detail': round(detail, 4), 'edge_proxy': round(edge, 4), 'reasons': reasons,
                      'fingerprint': fingerprint, 'thumbnail': output.getvalue()}
            self.decodes += 1
            self._cache[key] = result
            while len(self._cache) > self.cache_size:
                self._cache.popitem(last=False)
            return result

    def review(self, items: Sequence[ReviewedScreenshot], root: str | Path, *, version: Callable[[ReviewedScreenshot], int] = lambda _item: 0,
               cancelled: Callable[[], bool] = lambda: False, budget_seconds: float = 5) -> dict[str, Any]:
        start = time.monotonic()
        rows: list[dict[str, Any]] = []
        for item in items[:MAX_IMAGES]:
            if cancelled():
                raise InterruptedError('Analysis cancelled')
            row: dict[str, Any] = {'id': item.id, 'index': item.index, 'group': item.group, 'source': item.source,
                   'reasons': [], 'duplicate_of': [], 'text_or_credits': 'unknown', 'status': 'unknown'}
            if item.path is None:
                row['reasons'] = ['remote-image-not-fetched']
                row['version'] = hashlib.sha256(json.dumps(item.remote_image, sort_keys=True).encode()).hexdigest()
            elif time.monotonic() - start > budget_seconds:
                row['reasons'] = ['analysis-time-budget-exceeded']
            else:
                try:
                    result = self.inspect(item.path, root, version(item), cancelled)
                    row.update({k: v for k, v in result.items() if k != 'thumbnail'})
                    row['status'] = 'scored'
                except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
                    row['reasons'] = ['invalid-or-over-limit-local-image']
            rows.append(row)
        for index, row in enumerate(rows):
            if row['status'] != 'scored':
                continue
            for earlier in rows[:index]:
                if earlier['status'] != 'scored' or earlier['group'] != row['group']:
                    continue
                if (row['fingerprint'] ^ earlier['fingerprint']).bit_count() <= 4 and abs(row['brightness'] - earlier['brightness']) < 0.08 and abs(row['detail'] - earlier['detail']) < 0.05:
                    row['duplicate_of'].append(earlier['id'])
            if row['duplicate_of']:
                row['reasons'] = [*row['reasons'], 'perceptual-near-duplicate']
        for row in rows:
            row.pop('fingerprint', None)
            row['alternatives'] = [other['id'] for other in rows if other['id'] != row['id'] and other['group'] == row['group'] and other['status'] == 'scored' and not other['reasons']][:5]
        return {'images': rows, 'truncated': len(items) > MAX_IMAGES, 'elapsed_seconds': round(time.monotonic() - start, 4),
                'notice': 'Local heuristics only; dark art and intentional soft focus can be false positives. Text/credits unknown. Remote images are never fetched.'}
