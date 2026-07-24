from __future__ import annotations

from src.core.dedup import dedup_within_batch, filter_new_articles
from src.core.models import Article
from src.core.state import StateStore


def _article(url: str, title: str = "title", feed_name: str = "feed") -> Article:
    return Article(url=url, title=title, feed_name=feed_name)


def test_dedup_within_batch_removes_duplicate_urls():
    articles = [
        _article("https://example.com/a", title="first"),
        _article("https://example.com/a", title="duplicate"),
        _article("https://example.com/b"),
    ]
    result = dedup_within_batch(articles)
    assert len(result) == 2
    assert result[0].title == "first"


def test_filter_new_articles_excludes_delivered_within_ttl(tmp_path):
    db_path = tmp_path / "digest.db"
    with StateStore(db_path) as store:
        store.register_pending("https://example.com/a", "title a", "feed")
        store.mark_delivered("https://example.com/a")

        articles = [_article("https://example.com/a"), _article("https://example.com/b")]
        new_articles = filter_new_articles(articles, store, ttl_days=90)
        assert len(new_articles) == 1
        assert new_articles[0].url == "https://example.com/b"


def test_filter_new_articles_includes_pending_undelivered():
    # 配信前pending登録のみ(delivered_at未設定)の記事は、再度新着として扱われる
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        with StateStore(f"{tmp}/digest.db") as store:
            store.register_pending("https://example.com/a", "title a", "feed")
            articles = [_article("https://example.com/a")]
            new_articles = filter_new_articles(articles, store, ttl_days=90)
            assert len(new_articles) == 1
