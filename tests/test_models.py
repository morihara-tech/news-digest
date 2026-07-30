from __future__ import annotations

from src.core.models import Article


def test_article_new_scoring_fields_defaults():
    """重要度スコアリング用の新規フィールドはすべて未設定状態がデフォルトであること。"""
    article = Article(url="https://example.com/a", title="title", feed_name="feed")
    assert article.llm_importance_score is None
    assert article.importance_score is None
    assert article.emphasized is False


def test_article_instantiation_without_new_fields_still_works():
    """既存フィールドのみを指定したインスタンス化が引き続き動作すること（後方互換）。"""
    article = Article(
        url="https://example.com/b",
        title="title",
        feed_name="feed",
        category="tech",
        summary="summary text",
    )
    assert article.category == "tech"
    assert article.summary == "summary text"
    assert article.llm_importance_score is None
    assert article.importance_score is None
    assert article.emphasized is False


def test_article_new_scoring_fields_can_be_set():
    article = Article(
        url="https://example.com/c",
        title="title",
        feed_name="feed",
        llm_importance_score=80.0,
        importance_score=90.0,
        emphasized=True,
    )
    assert article.llm_importance_score == 80.0
    assert article.importance_score == 90.0
    assert article.emphasized is True
