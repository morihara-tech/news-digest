"""履歴参照系のMCPツールで使う純粋関数群。"""

from __future__ import annotations

from src.core.state import StateStore


def get_delivery_history(store: StateStore, limit: int = 20) -> list[dict]:
    rows = store.get_delivery_runs(limit=limit)
    return [
        {
            "id": row["id"],
            "run_at": row["run_at"],
            "status": row["status"],
            "article_count": row["article_count"],
            "error": row["error"],
        }
        for row in rows
    ]


def get_seen_articles(store: StateStore, limit: int = 100) -> list[dict]:
    rows = store.get_seen_articles(limit=limit)
    return [
        {
            "url": row["url"],
            "title": row["title"],
            "feed_name": row["feed_name"],
            "first_seen_at": row["first_seen_at"],
            "delivered_at": row["delivered_at"],
        }
        for row in rows
    ]
