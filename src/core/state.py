"""sqlite3による状態管理。

テーブル:
- seen_articles: URL基準の重複統合・既読管理（90日TTL）。配信成功後にのみ
  delivered_at を確定させる冪等設計。
- feedback: フィードバック記録。
- delivery_runs: 配信バッチの実行履歴。
- source_health: scraper種別フィードの取得結果（健全性）記録。
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_DB_PATH = Path("state/digest.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_articles (
    url TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    feed_name TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    delivered_at TEXT
);

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    feedback_type TEXT NOT NULL,
    value TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS delivery_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at TEXT NOT NULL,
    status TEXT NOT NULL,
    article_count INTEGER NOT NULL DEFAULT 0,
    error TEXT
);

CREATE TABLE IF NOT EXISTS source_health (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scraper_id TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    status TEXT NOT NULL,
    article_count INTEGER NOT NULL DEFAULT 0,
    error TEXT
);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class StateStore:
    """sqlite3を用いた状態ストア。呼び出し元がクローズ責任を持つ。"""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "StateStore":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # --- seen_articles -------------------------------------------------

    def is_recently_seen(self, url: str, ttl_days: int) -> bool:
        """90日TTL内に既に配信済み(delivered_at設定済み)の記事かどうかを判定する。

        delivered_at が未設定（配信前pending登録のみ）の記事は「未配信」扱いとし、
        再度配信対象になる（配信失敗時の再送を可能にするため）。
        """
        row = self._conn.execute(
            "SELECT delivered_at FROM seen_articles WHERE url = ?", (url,)
        ).fetchone()
        if row is None or row["delivered_at"] is None:
            return False
        delivered_at = datetime.fromisoformat(row["delivered_at"])
        cutoff = datetime.now(timezone.utc) - timedelta(days=ttl_days)
        return delivered_at >= cutoff

    def register_pending(self, url: str, title: str, feed_name: str) -> None:
        """配信前の仮登録。delivered_at は未設定のまま first_seen_at のみ記録する。
        既に存在する場合は何もしない（冪等）。"""
        self._conn.execute(
            """
            INSERT INTO seen_articles (url, title, feed_name, first_seen_at, delivered_at)
            VALUES (?, ?, ?, ?, NULL)
            ON CONFLICT(url) DO NOTHING
            """,
            (url, title, feed_name, _now_iso()),
        )
        self._conn.commit()

    def mark_delivered(self, url: str) -> None:
        """配信成功後にのみ呼び出し、delivered_at を確定させる。"""
        self._conn.execute(
            "UPDATE seen_articles SET delivered_at = ? WHERE url = ?",
            (_now_iso(), url),
        )
        self._conn.commit()

    def cleanup_expired(self, ttl_days: int) -> int:
        """TTLを過ぎたseen_articlesを削除する。削除件数を返す。"""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=ttl_days)).isoformat()
        cur = self._conn.execute(
            "DELETE FROM seen_articles WHERE delivered_at IS NOT NULL AND delivered_at < ?",
            (cutoff,),
        )
        self._conn.commit()
        return cur.rowcount

    def get_seen_articles(self, limit: int = 100) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM seen_articles ORDER BY first_seen_at DESC LIMIT ?", (limit,)
        ).fetchall()

    # --- feedback --------------------------------------------------------

    def add_feedback(self, url: str, feedback_type: str, value: str | None = None) -> int:
        cur = self._conn.execute(
            """
            INSERT INTO feedback (url, feedback_type, value, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (url, feedback_type, value, _now_iso()),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_feedback(self, limit: int = 100) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM feedback ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()

    # --- delivery_runs -----------------------------------------------------

    def start_run(self) -> int:
        cur = self._conn.execute(
            "INSERT INTO delivery_runs (run_at, status, article_count, error) VALUES (?, ?, ?, ?)",
            (_now_iso(), "running", 0, None),
        )
        self._conn.commit()
        return cur.lastrowid

    def finish_run(
        self, run_id: int, status: str, article_count: int, error: str | None = None
    ) -> None:
        self._conn.execute(
            "UPDATE delivery_runs SET status = ?, article_count = ?, error = ? WHERE id = ?",
            (status, article_count, error, run_id),
        )
        self._conn.commit()

    def get_delivery_runs(self, limit: int = 20) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM delivery_runs ORDER BY run_at DESC LIMIT ?", (limit,)
        ).fetchall()

    # --- source_health -----------------------------------------------------

    def record_source_health(
        self, scraper_id: str, status: str, article_count: int = 0, error: str | None = None
    ) -> None:
        """スクレイパーの取得結果を記録する。status は 'ok' | 'empty' | 'error'。"""
        self._conn.execute(
            "INSERT INTO source_health (scraper_id, checked_at, status, article_count, error) "
            "VALUES (?, ?, ?, ?, ?)",
            (scraper_id, _now_iso(), status, article_count, error),
        )
        self._conn.commit()

    def get_latest_source_health(self, limit: int = 100) -> list[sqlite3.Row]:
        """scraper_idごとの最新1件のみをchecked_at降順で返す。"""
        return self._conn.execute(
            """
            SELECT * FROM source_health
            WHERE id IN (SELECT MAX(id) FROM source_health GROUP BY scraper_id)
            ORDER BY checked_at DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()


@contextmanager
def open_state_store(db_path: str | Path = DEFAULT_DB_PATH):
    store = StateStore(db_path)
    try:
        yield store
    finally:
        store.close()
