"""重要度スコアリング: LLM生スコアとフィードバック補正値から最終スコアを算出する。

- LLMが返した生スコア（Article.llm_importance_score）を基準値とし、
  フィードバック学習（src/core/feedback.py の FeedbackWeights）による
  feed軸・keyword軸の補正値を加算する。
- ミュート対象（フィード or キーワード）は大きなペナルティを与えることで
  実質的に末尾へ追いやるが、記事自体は配信対象から除外しない
  （縮退配信と同様、「消さずに下げる」設計）。
- 最終的に articles をスコア降順で安定ソートする。
"""

from __future__ import annotations

from src.config import ScoringConfig
from src.core.feedback import FeedbackWeights
from src.core.models import Article


def clamp(value: float, lo: float, hi: float) -> float:
    """value を [lo, hi] の範囲に収める。"""
    return min(max(value, lo), hi)


def apply_scoring(
    articles: list[Article],
    weights: FeedbackWeights,
    scoring_config: ScoringConfig,
) -> None:
    """記事群に最終重要度スコア・強調フラグを設定し、スコア降順に並び替える（破壊的）。"""
    feedback_config = scoring_config.feedback

    for article in articles:
        base = (
            article.llm_importance_score
            if article.llm_importance_score is not None
            else scoring_config.default_score
        )

        delta = weights.feed_delta.get(article.feed_name, 0.0)
        for keyword in feedback_config.keywords:
            if keyword in article.title:
                delta += weights.keyword_delta.get(keyword, 0.0)
        delta = clamp(delta, -feedback_config.max_total_delta, feedback_config.max_total_delta)

        score = clamp(base + delta, scoring_config.score_min, scoring_config.score_max)

        muted = article.feed_name in weights.muted_feeds or any(
            keyword in article.title for keyword in weights.muted_keywords
        )
        if muted:
            score = base + delta - feedback_config.mute_penalty

        article.importance_score = score
        article.emphasized = (not muted) and score >= scoring_config.emphasis_threshold

    articles.sort(key=lambda a: a.importance_score, reverse=True)
