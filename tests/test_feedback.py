from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.config import ScoringConfig
from src.core.feedback import compute_feedback_weights
from src.core.state import StateStore


def _register_and_feedback(store: StateStore, url: str, title: str, feed_name: str, feedback_type: str) -> None:
    store.register_pending(url, title, feed_name)
    store.add_feedback(url, feedback_type)


def test_feed_axis_delta_sign_and_muted_feeds(tmp_path):
    db_path = tmp_path / "digest.db"
    with StateStore(db_path) as store:
        # feed-good: goodが多い -> deltaは正
        _register_and_feedback(store, "https://example.com/g1", "t1", "feed-good", "good")
        _register_and_feedback(store, "https://example.com/g2", "t2", "feed-good", "good")

        # feed-bad: badが多い -> deltaは負
        _register_and_feedback(store, "https://example.com/b1", "t3", "feed-bad", "bad")
        _register_and_feedback(store, "https://example.com/b2", "t4", "feed-bad", "bad")
        _register_and_feedback(store, "https://example.com/b3", "t5", "feed-bad", "bad")

        # feed-mute: mute_min_count(1)以上のmuteでmuted_feedsに入る
        _register_and_feedback(store, "https://example.com/m1", "t6", "feed-mute", "mute")

        scoring_config = ScoringConfig()
        weights = compute_feedback_weights(store, scoring_config)

        assert weights.feed_delta["feed-good"] > 0
        assert weights.feed_delta["feed-bad"] < 0
        assert "feed-mute" in weights.muted_feeds
        assert "feed-good" not in weights.muted_feeds


def test_keyword_axis_delta_and_muted_keywords(tmp_path):
    db_path = tmp_path / "digest.db"
    with StateStore(db_path) as store:
        _register_and_feedback(store, "https://example.com/k1", "AI最新動向まとめ", "feed-a", "good")
        _register_and_feedback(store, "https://example.com/k2", "ai関連ニュース", "feed-a", "good")
        _register_and_feedback(store, "https://example.com/k3", "スポーツ速報", "feed-b", "bad")
        _register_and_feedback(store, "https://example.com/k4", "AIによる自動化", "feed-a", "mute")

        scoring_config = ScoringConfig(
            feedback={"keywords": ["AI", "スポーツ"]}
        )
        weights = compute_feedback_weights(store, scoring_config)

        # "AI"は大小文字区別なくtitleにマッチ: good2, mute1 -> net=2>0 -> delta>0
        assert weights.keyword_delta["AI"] > 0
        assert "AI" in weights.muted_keywords

        # "スポーツ"はbadのみ -> delta<0
        assert weights.keyword_delta["スポーツ"] < 0
        assert "スポーツ" not in weights.muted_keywords


def test_empty_keywords_config_disables_keyword_axis(tmp_path):
    db_path = tmp_path / "digest.db"
    with StateStore(db_path) as store:
        _register_and_feedback(store, "https://example.com/k1", "AI最新動向", "feed-a", "good")

        scoring_config = ScoringConfig()
        weights = compute_feedback_weights(store, scoring_config)

        assert weights.keyword_delta == {}
        assert weights.muted_keywords == set()


def test_rows_without_feed_name_or_title_are_excluded(tmp_path):
    db_path = tmp_path / "digest.db"
    with StateStore(db_path) as store:
        # seen_articlesに存在しないurlでadd_feedbackを呼ぶと feed_name/title はNULLのまま登録される
        store.add_feedback("https://example.com/unknown", "good")

        scoring_config = ScoringConfig(feedback={"keywords": ["good"]})
        weights = compute_feedback_weights(store, scoring_config)

        assert weights.feed_delta == {}
        assert weights.muted_feeds == set()
        # keyword軸もtitleがNULLのため対象外
        assert weights.keyword_delta["good"] == 0.0
        assert weights.muted_keywords == set()


def test_lookback_days_excludes_old_feedback(tmp_path):
    db_path = tmp_path / "digest.db"
    with StateStore(db_path) as store:
        _register_and_feedback(store, "https://example.com/old", "old title", "feed-x", "good")

        # created_atを過去日時に書き換える(test_state.pyのTTLテストと同様の手法)
        old_date = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        store._conn.execute(
            "UPDATE feedback SET created_at = ? WHERE url = ?",
            (old_date, "https://example.com/old"),
        )
        store._conn.commit()

        _register_and_feedback(store, "https://example.com/new", "new title", "feed-x", "good")

        scoring_config = ScoringConfig(feedback={"lookback_days": 90})
        weights = compute_feedback_weights(store, scoring_config)

        # old feedbackが除外されnew feedbackのみ(good=1)が集計される -> net=1>0
        assert weights.feed_delta["feed-x"] > 0


def test_schema_migration_is_idempotent_across_multiple_opens(tmp_path):
    db_path = tmp_path / "digest.db"

    with StateStore(db_path) as store:
        store.register_pending("https://example.com/a", "title", "feed")
        store.add_feedback("https://example.com/a", "good")

    # 同じdb_pathで複数回開いてもエラーにならず、既存行が壊れないこと
    with StateStore(db_path) as store:
        rows = store.get_feedback()
        assert len(rows) == 1
        assert rows[0]["feed_name"] == "feed"
        assert rows[0]["title"] == "title"

    with StateStore(db_path) as store:
        rows = store.get_feedback()
        assert len(rows) == 1
