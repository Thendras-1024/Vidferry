import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sau_backend


class _Cursor:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=()):
        self.calls.append((sql, params))

    def fetchone(self):
        return None if len(self.calls) == 1 else [1]


def test_publish_archive_serializes_postgres_datetime_metadata():
    cursor = _Cursor()
    sau_backend._archive_published_material(
        cursor,
        {"source_video_id": "video-1", "metadata": {}},
        {"id": "video-1", "publishedAt": datetime(2026, 8, 1, 14, 0)},
        "抖音",
        "2026-08-01 14:00:00",
        platform_type=3,
    )

    metadata = json.loads(cursor.calls[-1][1][16])
    assert metadata["sourceVideo"]["publishedAt"] == "2026-08-01 14:00:00"
