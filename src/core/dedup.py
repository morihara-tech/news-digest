"""URL基準の重複統合ロジック。

- 同一バッチ内で同じURLが複数フィードから取得された場合は1件に統合する。
- 90日TTL以内に配信済みのURLは新着扱いしない（state.StateStore経由で判定）。
"""

from __future__ import annotations

from src.core.models import Article
from src.core.state import StateStore


def dedup_within_batch(articles: list[Article]) -> list[Article]:
    """同一バッチ内でのURL重複を除去する（最初に出現したものを残す）。"""
    seen: set[str] = set()
    result: list[Article] = []
    for article in articles:
        key = article.normalized_url()
        if key in seen:
            continue
        seen.add(key)
        result.append(article)
    return result


def filter_new_articles(
    articles: list[Article], store: StateStore, ttl_days: int
) -> list[Article]:
    """既に(TTL内に)配信済みの記事を除外し、新着のみを返す。"""
    deduped = dedup_within_batch(articles)
    return [a for a in deduped if not store.is_recently_seen(a.normalized_url(), ttl_days)]
