"""feedparserベースのRSS/Atomフィード取得・パースモジュール。

テストではネットワークに依存しないよう、feedparser.parse() には
ローカルXML文字列やファイルパスを直接渡せる（feedparserの仕様上、
URL/ファイルパス/XML文字列のいずれも受け付ける）。
"""

from __future__ import annotations

import logging

import feedparser

from src.config import FeedConfig, FiltersConfig
from src.core.models import Article

logger = logging.getLogger(__name__)


def fetch_feed_entries(feed: FeedConfig, source: str | None = None) -> list[Article]:
    """1フィード分の記事一覧を取得する。

    source を指定するとその文字列/パス/URLをfeedparserに渡す
    （テスト時にローカルXML固定ファイルを注入するために使う）。
    省略時は feed.url を使う。
    """
    target = source if source is not None else feed.url
    parsed = feedparser.parse(target)

    if parsed.bozo and not parsed.entries:
        logger.warning(
            "フィード %s (%s) のパースに失敗しました: %s",
            feed.name,
            feed.url,
            getattr(parsed, "bozo_exception", "unknown error"),
        )
        return []

    articles: list[Article] = []
    for entry in parsed.entries:
        url = getattr(entry, "link", None)
        title = getattr(entry, "title", "(no title)")
        if not url:
            continue
        summary_source = getattr(entry, "summary", "") or getattr(entry, "description", "")
        published_at = getattr(entry, "published", None) or getattr(entry, "updated", None)
        articles.append(
            Article(
                url=url,
                title=title,
                feed_name=feed.name,
                category=feed.category,
                summary_source=summary_source,
                published_at=published_at,
            )
        )
    return articles


def apply_filters(articles: list[Article], filters: FiltersConfig) -> list[Article]:
    """include_keywords / exclude_keywords によるフィルタ適用。

    - include_keywords が空配列なら全通過。非空ならタイトルまたは本文抜粋に
      いずれかを含む記事のみ通過。
    - exclude_keywords はいずれかを含む記事を除外。
    """
    result: list[Article] = []
    for article in articles:
        haystack = f"{article.title}\n{article.summary_source}"

        if filters.include_keywords:
            if not any(kw in haystack for kw in filters.include_keywords):
                continue

        if filters.exclude_keywords:
            if any(kw in haystack for kw in filters.exclude_keywords):
                continue

        result.append(article)
    return result


def fetch_all(feeds: list[FeedConfig], global_filters: FiltersConfig) -> list[Article]:
    """有効な全フィードを取得し、フィード単位/グローバルのフィルタを適用して返す。"""
    all_articles: list[Article] = []
    for feed in feeds:
        if not feed.enabled:
            continue
        try:
            articles = fetch_feed_entries(feed)
            effective_filters = feed.effective_filters(global_filters)
            articles = apply_filters(articles, effective_filters)
        except Exception:  # noqa: BLE001 - 1フィードの想定外失敗が他フィードをブロックしない
            logger.exception(
                "フィード %s (%s) の取得中に予期しないエラーが発生しました", feed.name, feed.url
            )
            articles = []
        all_articles.extend(articles)
    return all_articles
