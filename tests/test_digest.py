from __future__ import annotations

from src.config import DigestConfig
from src.core.digest import build_digest, mark_cost_overflow, summarize_articles
from src.core.models import Article
from tests.mock_llm_provider import MockLLMProvider


def _article(url: str, feed_name: str = "feed", category: str = "tech") -> Article:
    return Article(url=url, title=f"title-{url}", feed_name=feed_name, category=category)


def test_summarize_articles_success():
    articles = [_article("https://example.com/a"), _article("https://example.com/b")]
    provider = MockLLMProvider()
    summarize_articles(articles, provider)
    assert all(a.summary is not None for a in articles)
    assert all(not a.degraded for a in articles)


def test_summarize_articles_degrades_on_failure():
    articles = [_article("https://example.com/a"), _article("https://example.com/b")]
    provider = MockLLMProvider(fail_urls={"https://example.com/a"})
    summarize_articles(articles, provider)

    failed = [a for a in articles if a.url == "https://example.com/a"][0]
    ok = [a for a in articles if a.url == "https://example.com/b"][0]
    assert failed.degraded is True
    assert failed.summary is None
    assert ok.degraded is False
    assert ok.summary is not None


def test_summarize_articles_degrades_on_provider_batch_exception():
    articles = [_article("https://example.com/a")]
    provider = MockLLMProvider(raise_on_batch=True)
    summarize_articles(articles, provider)
    assert articles[0].degraded is True
    assert articles[0].summary is None


def test_summarize_articles_skips_already_degraded_articles():
    """コスト上限超過等で既にdegraded=Trueな記事はプロバイダー呼び出し対象から除外される。"""
    articles = [_article(f"https://example.com/{i}") for i in range(3)]
    articles[2].degraded = True
    articles[2].degraded_reason = "cost_limit_exceeded"

    provider = MockLLMProvider()
    summarize_articles(articles, provider)

    assert articles[0].summary is not None
    assert articles[1].summary is not None
    # 既にdegradedだった記事はsummarize_batchに渡されず、summaryも設定されない
    assert articles[2].degraded is True
    assert articles[2].degraded_reason == "cost_limit_exceeded"
    assert articles[2].summary is None
    called_urls = set(provider.summarize_calls)
    assert articles[2].normalized_url() not in called_urls


def test_mark_cost_overflow_marks_articles_beyond_limit():
    articles = [_article(f"https://example.com/{i}") for i in range(5)]
    mark_cost_overflow(articles, limit=3)

    kept = articles[:3]
    overflow = articles[3:]
    assert all(a.degraded is False for a in kept)
    assert all(a.degraded is True for a in overflow)
    assert all(a.degraded_reason == "cost_limit_exceeded" for a in overflow)


def test_build_digest_applies_max_articles_and_carries_over():
    articles = [_article(f"https://example.com/{i}") for i in range(5)]
    digest_config = DigestConfig(max_articles=3, group_by="none")
    result = build_digest(articles, digest_config)
    assert len(result.articles) == 3
    assert result.carried_over_count == 2


def test_build_digest_groups_by_feed():
    articles = [
        _article("https://example.com/a", feed_name="Feed A"),
        _article("https://example.com/b", feed_name="Feed B"),
        _article("https://example.com/c", feed_name="Feed A"),
    ]
    digest_config = DigestConfig(max_articles=10, group_by="feed")
    result = build_digest(articles, digest_config)
    assert set(result.groups.keys()) == {"Feed A", "Feed B"}
    assert len(result.groups["Feed A"]) == 2
    assert len(result.groups["Feed B"]) == 1
