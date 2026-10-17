"""Small SQLite response cache, so repeat lookups don't re-hit the same sites."""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


@dataclass
class CachedResponse:
    url: str
    status: int
    content_type: str
    text: str
    fetched_at: datetime


class ResponseCache:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS responses (
                    key TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    status INTEGER NOT NULL,
                    content_type TEXT NOT NULL,
                    text TEXT NOT NULL,
                    fetched_at TEXT NOT NULL
                )"""
            )
            self._conn.commit()

    def get(self, key: str, ttl: timedelta) -> CachedResponse | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT url, status, content_type, text, fetched_at FROM responses WHERE key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        fetched_at = datetime.fromisoformat(row[4])
        if datetime.now(timezone.utc) - fetched_at > ttl:
            return None
        return CachedResponse(row[0], row[1], row[2], row[3], fetched_at)

    def put(self, key: str, resp: CachedResponse) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO responses VALUES (?, ?, ?, ?, ?, ?)",
                (key, resp.url, resp.status, resp.content_type, resp.text, resp.fetched_at.isoformat()),
            )
            self._conn.commit()
