from __future__ import annotations

from src.config import ScoringConfig, ScoringFeedbackConfig
from src.core.feedback import FeedbackWeights
from src.core.models import Article
from src.core.scoring import apply_scoring, clamp


def _article(url: str, title: str, feed_name: str, llm_score: float | None) -> Article:
    return Article(
        url=url, title=title, feed_name=feed_name, llm_importance_score=llm_score
    )


def _empty_weights() -> FeedbackWeights:
    return FeedbackWeights(feed_delta={}, keyword_delta={}, muted_feeds=set(), muted_keywords=set())


def test_clamp():
    assert clamp(5, 0, 10) == 5
    assert clamp(-5, 0, 10) == 0
    assert clamp(15, 0, 10) == 10


def test_apply_scoring_sorts_by_score_descending():
    articles = [
        _article("https://example.com/a", "A", "feed", 30.0),
        _article("https://example.com/b", "B", "feed", 90.0),
        _article("https://example.com/c", "C", "feed", 60.0),
    ]
    scoring_config = ScoringConfig()
    apply_scoring(articles, _empty_weights(), scoring_config)

    assert [a.url for a in articles] == [
        "https://example.com/b",
        "https://example.com/c",
        "https://example.com/a",
    ]


def test_apply_scoring_sets_emphasized_when_over_threshold():
    articles = [
        _article("https://example.com/a", "A", "feed", 80.0),
        _article("https://example.com/b", "B", "feed", 50.0),
    ]
    scoring_config = ScoringConfig(emphasis_threshold=70.0)
    apply_scoring(articles, _empty_weights(), scoring_config)

    by_url = {a.url: a for a in articles}
    assert by_url["https://example.com/a"].emphasized is True
    assert by_url["https://example.com/b"].emphasized is False


def test_apply_scoring_no_feedback_uses_llm_score_only():
    """フィードバック0件(feed_delta/keyword_deltaが空、muted集合も空)の場合、
    deltaは常に0でLLM算出スコアのみで並ぶ。"""
    articles = [
        _article("https://example.com/a", "A", "feed-x", 10.0),
        _article("https://example.com/b", "B", "feed-y", 99.0),
    ]
    scoring_config = ScoringConfig()
    apply_scoring(articles, _empty_weights(), scoring_config)

    by_url = {a.url: a for a in articles}
    assert by_url["https://example.com/a"].importance_score == 10.0
    assert by_url["https://example.com/b"].importance_score == 99.0


def test_apply_scoring_default_score_applied_when_llm_score_missing():
    """llm_importance_scoreがNone(スコア算出失敗)の場合、default_scoreが適用され
    記事が欠落なく残る。"""
    articles = [
        _article("https://example.com/a", "A", "feed", None),
        _article("https://example.com/b", "B", "feed", 90.0),
    ]
    scoring_config = ScoringConfig(default_score=50.0)
    apply_scoring(articles, _empty_weights(), scoring_config)

    assert len(articles) == 2
    by_url = {a.url: a for a in articles}
    assert by_url["https://example.com/a"].importance_score == 50.0


def test_apply_scoring_non_muted_score_within_range():
    """非ミュート記事: importance_score は [score_min, score_max] に収まる。"""
    articles = [
        _article("https://example.com/a", "A", "feed-good", 95.0),
        _article("https://example.com/b", "B", "feed-bad", 5.0),
    ]
    weights = FeedbackWeights(
        feed_delta={"feed-good": 40.0, "feed-bad": -40.0},
        keyword_delta={},
        muted_feeds=set(),
        muted_keywords=set(),
    )
    scoring_config = ScoringConfig(score_min=0.0, score_max=100.0)
    apply_scoring(articles, weights, scoring_config)

    for article in articles:
        assert scoring_config.score_min <= article.importance_score <= scoring_config.score_max


def test_apply_scoring_muted_feed_ranked_last_and_not_emphasized_and_kept():
    """ミュート記事はscore=clamp(base+delta)-mute_penaltyとなり、
    mute_penalty(1000) > score_max-score_min(100) であるため必ず最下位に来る。
    かつ記事は除外されず、emphasizedはFalse固定。"""
    articles = [
        _article("https://example.com/muted", "Muted", "muted-feed", 99.0),
        _article("https://example.com/normal", "Normal", "normal-feed", 1.0),
    ]
    weights = FeedbackWeights(
        feed_delta={},
        keyword_delta={},
        muted_feeds={"muted-feed"},
        muted_keywords=set(),
    )
    scoring_config = ScoringConfig()
    apply_scoring(articles, weights, scoring_config)

    assert len(articles) == 2
    # 最下位に来ている
    assert articles[-1].url == "https://example.com/muted"

    muted_article = [a for a in articles if a.url == "https://example.com/muted"][0]
    # base=99.0, delta=0.0 -> clamp(99,0,100)=99 -> 99 - 1000 = -901 (下限クランプなし)
    assert muted_article.importance_score == 99.0 - scoring_config.feedback.mute_penalty
    assert muted_article.emphasized is False


def test_apply_scoring_muted_keyword_applies_penalty():
    articles = [
        _article("https://example.com/a", "速報: 重要ニュース", "feed", 90.0),
    ]
    weights = FeedbackWeights(
        feed_delta={},
        keyword_delta={},
        muted_feeds=set(),
        muted_keywords={"速報"},
    )
    scoring_config = ScoringConfig()
    apply_scoring(articles, weights, scoring_config)

    assert articles[0].importance_score == 90.0 - scoring_config.feedback.mute_penalty
    assert articles[0].emphasized is False


def test_apply_scoring_delta_clamped_by_max_total_delta():
    """feed_delta+keyword_deltaの合計がmax_total_deltaを超える場合、
    apply_scoring単体でクランプされることを検証する。"""
    articles = [
        _article("https://example.com/a", "AI速報", "feed", 50.0),
    ]
    weights = FeedbackWeights(
        feed_delta={"feed": 100.0},
        keyword_delta={"AI": 100.0},
        muted_feeds=set(),
        muted_keywords=set(),
    )
    scoring_config = ScoringConfig(
        score_min=0.0,
        score_max=100.0,
        feedback=ScoringFeedbackConfig(keywords=["AI"], max_total_delta=40.0),
    )
    apply_scoring(articles, weights, scoring_config)

    # delta = 100+100 = 200 -> clamp(-40,40) = 40 -> score = clamp(50+40, 0, 100) = 90
    assert articles[0].importance_score == 90.0


def test_apply_scoring_delta_clamped_negative_side():
    articles = [
        _article("https://example.com/a", "A", "feed", 50.0),
    ]
    weights = FeedbackWeights(
        feed_delta={"feed": -100.0},
        keyword_delta={},
        muted_feeds=set(),
        muted_keywords=set(),
    )
    scoring_config = ScoringConfig(
        score_min=0.0, score_max=100.0, feedback=ScoringFeedbackConfig(max_total_delta=40.0)
    )
    apply_scoring(articles, weights, scoring_config)

    # delta = -100 -> clamp(-40,40) = -40 -> score = clamp(50-40,0,100) = 10
    assert articles[0].importance_score == 10.0
