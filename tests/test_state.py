from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.core.state import StateStore


def test_register_pending_then_mark_delivered_idempotent(tmp_path):
    db_path = tmp_path / "digest.db"
    with StateStore(db_path) as store:
        store.register_pending("https://example.com/a", "title", "feed")
        assert store.is_recently_seen("https://example.com/a", ttl_days=90) is False

        store.mark_delivered("https://example.com/a")
        assert store.is_recently_seen("https://example.com/a", ttl_days=90) is True

        # 再度register_pendingしても既存レコードは変わらない（冪等）
        store.register_pending("https://example.com/a", "different title", "feed")
        rows = store.get_seen_articles()
        assert len(rows) == 1
        assert rows[0]["title"] == "title"


def test_delivered_before_ttl_cutoff_is_not_recently_seen(tmp_path):
    db_path = tmp_path / "digest.db"
    with StateStore(db_path) as store:
        store.register_pending("https://example.com/a", "title", "feed")
        store.mark_delivered("https://example.com/a")

        # TTLを過ぎたことにするため直接delivered_atを過去日時に書き換える
        old_date = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        store._conn.execute(
            "UPDATE seen_articles SET delivered_at = ? WHERE url = ?",
            (old_date, "https://example.com/a"),
        )
        store._conn.commit()

        assert store.is_recently_seen("https://example.com/a", ttl_days=90) is False


def test_cleanup_expired_removes_old_entries(tmp_path):
    db_path = tmp_path / "digest.db"
    with StateStore(db_path) as store:
        store.register_pending("https://example.com/a", "title", "feed")
        store.mark_delivered("https://example.com/a")
        old_date = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        store._conn.execute(
            "UPDATE seen_articles SET delivered_at = ? WHERE url = ?",
            (old_date, "https://example.com/a"),
        )
        store._conn.commit()

        removed = store.cleanup_expired(ttl_days=90)
        assert removed == 1
        assert store.get_seen_articles() == []


def test_feedback_and_delivery_runs(tmp_path):
    db_path = tmp_path / "digest.db"
    with StateStore(db_path) as store:
        feedback_id = store.add_feedback("https://example.com/a", "good", "helpful")
        assert feedback_id is not None
        feedback_rows = store.get_feedback()
        assert len(feedback_rows) == 1
        assert feedback_rows[0]["feedback_type"] == "good"

        run_id = store.start_run()
        store.finish_run(run_id, "delivered", 3)
        runs = store.get_delivery_runs()
        assert len(runs) == 1
        assert runs[0]["status"] == "delivered"
        assert runs[0]["article_count"] == 3
