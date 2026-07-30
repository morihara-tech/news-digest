"""ダイジェスト組み立てロジック。

- LLMProviderによる要約を行い、失敗・コスト上限超過時は縮退配信
  （タイトル+リンクのみ）にフォールバックさせるためのフラグを立てる。
- config.digest.max_articles による配信件数上限を適用する。
  上限を超えた分は「削除」ではなく「今回は配信対象から外す」だけであり、
  該当記事は state.StateStore 上で delivered_at が確定しないため、
  次回以降のバッチ実行で自然に再度候補となる（=持ち越し）。
  README にもこの挙動を明記すること。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.config import DigestConfig
from src.core.models import Article
from src.llm.base import LLMProvider


def mark_cost_overflow(pool: list[Article], limit: int) -> list[Article]:
    """要約対象記事数の上限（コスト上限）を超えた記事にdegradedマークを立てる。

    サイトごとに分割する前の、サイト横断の全体プールに対して1回だけ適用する。
    """
    overflow = pool[limit:]
    for article in overflow:
        article.degraded = True
        article.degraded_reason = "cost_limit_exceeded"
    return pool


def summarize_articles(articles: list[Article], provider: LLMProvider) -> list[Article]:
    """記事群を要約する。要約失敗時は縮退配信フラグを立てる。

    既に degraded=True（コスト上限超過等）の記事はプロバイダー呼び出し対象から
    除外し、残りだけを provider.summarize_batch() に渡す。
    """
    if not articles:
        return articles

    to_summarize = [a for a in articles if not a.degraded]

    if not to_summarize:
        return articles

    try:
        results = provider.summarize_batch(to_summarize)
    except Exception as exc:  # noqa: BLE001 - プロバイダー全体の失敗も縮退配信に委ねる
        for article in to_summarize:
            article.degraded = True
            article.degraded_reason = f"summarize_failed: {exc}"
        return articles

    for article in to_summarize:
        key = article.normalized_url()
        if key in results and results[key]:
            result = results[key]
            article.summary = result.summary
            article.llm_importance_score = result.importance_score
        else:
            article.degraded = True
            article.degraded_reason = "summarize_failed"

    return articles


@dataclass
class DigestResult:
    articles: list[Article]
    groups: dict[str, list[Article]] = field(default_factory=dict)
    carried_over_count: int = 0


def build_digest(articles: list[Article], digest_config: DigestConfig) -> DigestResult:
    """配信件数上限・グルーピングを適用してダイジェストを組み立てる。"""
    limited = articles[: digest_config.max_articles]
    carried_over_count = max(0, len(articles) - digest_config.max_articles)

    if digest_config.group_by == "feed":
        key_fn = lambda a: a.feed_name  # noqa: E731
    elif digest_config.group_by == "category":
        key_fn = lambda a: a.category  # noqa: E731
    else:
        key_fn = lambda a: "articles"  # noqa: E731

    groups: dict[str, list[Article]] = {}
    for article in limited:
        groups.setdefault(key_fn(article), []).append(article)

    return DigestResult(articles=limited, groups=groups, carried_over_count=carried_over_count)
