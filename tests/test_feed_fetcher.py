from __future__ import annotations

from src.config import FeedConfig, FiltersConfig
from src.core.feed_fetcher import apply_filters, fetch_all, fetch_feed_entries


def test_fetch_feed_entries_rss(fixtures_dir):
    feed = FeedConfig(name="Tech Sample", url="https://example.com/rss", category="tech")
    articles = fetch_feed_entries(feed, source=str(fixtures_dir / "rss_tech.xml"))
    assert len(articles) == 3
    assert articles[0].title == "AWSの新サービスが発表されました"
    assert articles[0].url == "https://example.com/tech/aws-new-service"
    assert articles[0].feed_name == "Tech Sample"
    assert articles[0].category == "tech"


def test_fetch_feed_entries_atom(fixtures_dir):
    feed = FeedConfig(name="Publickey Sample", url="https://example.com/atom", category="tech")
    articles = fetch_feed_entries(feed, source=str(fixtures_dir / "atom_publickey.xml"))
    assert len(articles) == 2
    assert articles[0].url == "https://example.com/publickey/k8s-new-approach"


def test_apply_filters_include_keywords(fixtures_dir):
    feed = FeedConfig(name="Tech Sample", url="https://example.com/rss", category="tech")
    articles = fetch_feed_entries(feed, source=str(fixtures_dir / "rss_tech.xml"))
    filters = FiltersConfig(include_keywords=["Kubernetes"], exclude_keywords=[])
    filtered = apply_filters(articles, filters)
    # "AWSの新サービス"記事の本文にも"Kubernetes"への言及があるため2件がマッチする
    assert len(filtered) == 2
    assert all("Kubernetes" in f"{a.title}\n{a.summary_source}" for a in filtered)


def test_apply_filters_exclude_keywords(fixtures_dir):
    feed = FeedConfig(name="Tech Sample", url="https://example.com/rss", category="tech")
    articles = fetch_feed_entries(feed, source=str(fixtures_dir / "rss_tech.xml"))
    filters = FiltersConfig(include_keywords=[], exclude_keywords=["広告"])
    filtered = apply_filters(articles, filters)
    assert len(filtered) == 2
    assert all("広告" not in a.title for a in filtered)


def test_apply_filters_empty_include_passes_all(fixtures_dir):
    feed = FeedConfig(name="Tech Sample", url="https://example.com/rss", category="tech")
    articles = fetch_feed_entries(feed, source=str(fixtures_dir / "rss_tech.xml"))
    filters = FiltersConfig(include_keywords=[], exclude_keywords=[])
    filtered = apply_filters(articles, filters)
    assert len(filtered) == len(articles)


def test_feed_level_filters_override_global(monkeypatch, fixtures_dir):
    # フィード単位のfiltersがグローバルを上書きすることを確認する
    feed = FeedConfig(
        name="Publickey Sample",
        url="https://example.com/atom",
        category="tech",
        filters=FiltersConfig(include_keywords=["AWS", "GCP"]),
    )
    articles = fetch_feed_entries(feed, source=str(fixtures_dir / "atom_publickey.xml"))
    global_filters = FiltersConfig(include_keywords=[], exclude_keywords=["Kubernetes"])
    effective = feed.effective_filters(global_filters)
    filtered = apply_filters(articles, effective)
    # グローバルのexclude_keywordsは無視され、フィード単位のinclude_keywordsのみ適用される
    assert len(filtered) == 1
    assert "データベース" in filtered[0].title
