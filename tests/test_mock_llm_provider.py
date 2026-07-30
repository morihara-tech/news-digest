"""MockLLMProviderのユニットテスト。

scores指定時に追加のLLM呼び出しが発生しないこと（要約とスコア取得が
同一呼び出しであること）を、summarize_calls の呼び出し回数が記事数と
一致することで検証する。
"""

from __future__ import annotations

from src.core.models import Article
from src.llm.base import SummaryResult
from tests.mock_llm_provider import MockLLMProvider


def _articles() -> list[Article]:
    return [
        Article(url="https://example.com/a", title="Title A", feed_name="feed"),
        Article(url="https://example.com/b", title="Title B", feed_name="feed"),
    ]


def test_summarize_batch_returns_scores_without_extra_calls():
    articles = _articles()
    provider = MockLLMProvider(scores={"https://example.com/a": 90.0, "https://example.com/b": 10.0})

    results = provider.summarize_batch(articles)

    # 追加のLLM呼び出しは発生せず、記事数と summarize_calls の回数が一致する
    # （要約とスコア取得が同一呼び出しであることの検証）。
    assert len(provider.summarize_calls) == len(articles)
    assert results["https://example.com/a"] == SummaryResult(
        summary="要約: Title A", importance_score=90.0
    )
    assert results["https://example.com/b"] == SummaryResult(
        summary="要約: Title B", importance_score=10.0
    )


def test_summarize_batch_without_scores_returns_none_importance():
    articles = _articles()
    provider = MockLLMProvider()

    results = provider.summarize_batch(articles)

    assert len(provider.summarize_calls) == len(articles)
    assert all(r.importance_score is None for r in results.values())


def test_summarize_single_call_returns_score_without_extra_calls():
    provider = MockLLMProvider(scores={"https://example.com/a": 55.0})
    article = _articles()[0]

    result = provider.summarize(article)

    assert len(provider.summarize_calls) == 1
    assert result == SummaryResult(summary="要約: Title A", importance_score=55.0)
