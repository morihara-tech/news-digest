from __future__ import annotations

from datetime import datetime, timezone

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


def test_fetch_feed_entries_parses_published_parsed_rss(fixtures_dir):
    feed = FeedConfig(name="Tech Sample", url="https://example.com/rss", category="tech")
    articles = fetch_feed_entries(feed, source=str(fixtures_dir / "rss_tech.xml"))
    assert articles[0].published_parsed == datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def test_fetch_feed_entries_parses_published_parsed_atom(fixtures_dir):
    feed = FeedConfig(name="Publickey Sample", url="https://example.com/atom", category="tech")
    articles = fetch_feed_entries(feed, source=str(fixtures_dir / "atom_publickey.xml"))
    assert articles[0].published_parsed == datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def test_fetch_feed_entries_missing_pubdate_yields_none(fixtures_dir):
    feed = FeedConfig(name="No PubDate Sample", url="https://example.com/no-pubdate", category="tech")
    articles = fetch_feed_entries(feed, source=str(fixtures_dir / "rss_no_pubdate.xml"))
    assert len(articles) == 1
    assert articles[0].published_parsed is None


def test_apply_filters_max_age_days_excludes_old_articles(fixtures_dir):
    feed = FeedConfig(name="Tech Sample", url="https://example.com/rss", category="tech")
    articles = fetch_feed_entries(feed, source=str(fixtures_dir / "rss_tech.xml"))
    # 記事は2024-01-01付近。基準時刻を2024-01-10とし、max_age_days=5で全件古すぎるため除外される。
    now = datetime(2024, 1, 10, tzinfo=timezone.utc)
    filters = FiltersConfig(max_age_days=5)
    filtered = apply_filters(articles, filters, now=now)
    assert filtered == []


def test_apply_filters_max_age_days_keeps_recent_articles(fixtures_dir):
    feed = FeedConfig(name="Tech Sample", url="https://example.com/rss", category="tech")
    articles = fetch_feed_entries(feed, source=str(fixtures_dir / "rss_tech.xml"))
    # 基準時刻を記事日時の翌日とし、max_age_days=5なら除外されない。
    now = datetime(2024, 1, 2, tzinfo=timezone.utc)
    filters = FiltersConfig(max_age_days=5)
    filtered = apply_filters(articles, filters, now=now)
    assert len(filtered) == len(articles)


def test_apply_filters_max_age_days_none_means_no_date_filter(fixtures_dir):
    feed = FeedConfig(name="Tech Sample", url="https://example.com/rss", category="tech")
    articles = fetch_feed_entries(feed, source=str(fixtures_dir / "rss_tech.xml"))
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    filters = FiltersConfig(max_age_days=None)
    filtered = apply_filters(articles, filters, now=now)
    assert len(filtered) == len(articles)


def test_apply_filters_max_age_days_combined_with_keywords(fixtures_dir):
    feed = FeedConfig(name="Tech Sample", url="https://example.com/rss", category="tech")
    articles = fetch_feed_entries(feed, source=str(fixtures_dir / "rss_tech.xml"))
    now = datetime(2024, 1, 2, tzinfo=timezone.utc)
    # include_keywords=["Kubernetes"]で2件、max_age_days=5(全件が該当)を併用してもAND条件で2件のまま。
    filters = FiltersConfig(include_keywords=["Kubernetes"], max_age_days=5)
    filtered = apply_filters(articles, filters, now=now)
    assert len(filtered) == 2

    # max_age_days=0（基準時刻より前は全て除外）にすると、キーワード一致でも0件になる。
    strict_now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    strict_filters = FiltersConfig(include_keywords=["Kubernetes"], max_age_days=1)
    strict_filtered = apply_filters(articles, strict_filters, now=strict_now)
    assert strict_filtered == []


def test_apply_filters_max_age_days_passes_through_unparseable_dates(fixtures_dir):
    feed = FeedConfig(name="No PubDate Sample", url="https://example.com/no-pubdate", category="tech")
    articles = fetch_feed_entries(feed, source=str(fixtures_dir / "rss_no_pubdate.xml"))
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    filters = FiltersConfig(max_age_days=1)
    filtered = apply_filters(articles, filters, now=now)
    # 発行日パース不能な記事は除外せず素通りする
    assert len(filtered) == 1


def test_fetch_all_applies_global_max_age_days(fixtures_dir):
    # フィクスチャの記事は2024-01-01付近で固定されており、実行時刻(現在)からは
    # 十分に古いため、短いmax_age_daysを指定すると全件除外される。
    feed = FeedConfig(name="Tech Sample", url=str(fixtures_dir / "rss_tech.xml"), category="tech")
    global_filters = FiltersConfig(max_age_days=30)
    articles = fetch_all([feed], global_filters)
    assert articles == []


def test_fetch_all_feed_level_max_age_days_overrides_global(fixtures_dir):
    # フィード単位のfiltersがグローバルのmax_age_daysを上書き（緩和）することを確認する
    feed = FeedConfig(
        name="Tech Sample",
        url=str(fixtures_dir / "rss_tech.xml"),
        category="tech",
        filters=FiltersConfig(max_age_days=36500),
    )
    global_filters = FiltersConfig(max_age_days=30)
    articles = fetch_all([feed], global_filters)
    assert len(articles) == 3


def test_feed_level_filters_without_max_age_days_disables_global_max_age_days(fixtures_dir):
    # フィード単位filtersにキーワードのみ指定しmax_age_daysを書かない場合、
    # effective_filters()の全置換セマンティクスにより、そのフィードでは
    # グローバルのmax_age_daysが無効化される（既存のtest_feed_level_filters_override_globalと同種の回帰テスト）。
    feed = FeedConfig(
        name="Tech Sample",
        url="https://example.com/rss",
        category="tech",
        filters=FiltersConfig(include_keywords=["Kubernetes"]),
    )
    articles = fetch_feed_entries(feed, source=str(fixtures_dir / "rss_tech.xml"))
    global_filters = FiltersConfig(max_age_days=1)
    effective = feed.effective_filters(global_filters)
    assert effective.max_age_days is None

    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    filtered = apply_filters(articles, effective, now=now)
    # max_age_daysが無効化されているため、キーワード一致の2件がそのまま残る
    assert len(filtered) == 2


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
