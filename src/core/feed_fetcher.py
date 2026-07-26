"""feedparserベースのRSS/Atomフィード取得・パースモジュール。

テストではネットワークに依存しないよう、feedparser.parse() には
ローカルXML文字列やファイルパスを直接渡せる（feedparserの仕様上、
URL/ファイルパス/XML文字列のいずれも受け付ける）。
"""

from __future__ import annotations

import calendar
import logging
import time
from datetime import datetime, timedelta, timezone

import feedparser

from src.config import FeedConfig, FiltersConfig
from src.core.models import Article
from src.core.scraper_fetcher import fetch_via_scraper
from src.core.state import StateStore

logger = logging.getLogger(__name__)


def _to_utc_datetime(parsed_time: time.struct_time | None) -> datetime | None:
    """feedparserの *_parsed（UTC正規化済みのtime.struct_time）をdatetimeに変換する。"""
    if parsed_time is None:
        return None
    timestamp = calendar.timegm(parsed_time)
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


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
        published_parsed = _to_utc_datetime(
            getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
        )
        articles.append(
            Article(
                url=url,
                title=title,
                feed_name=feed.name,
                category=feed.category,
                summary_source=summary_source,
                published_at=published_at,
                published_parsed=published_parsed,
            )
        )
    return articles


def apply_filters(
    articles: list[Article], filters: FiltersConfig, now: datetime | None = None
) -> list[Article]:
    """include_keywords / exclude_keywords / max_age_days によるフィルタ適用。

    - include_keywords が空配列なら全通過。非空ならタイトルまたは本文抜粋に
      いずれかを含む記事のみ通過。
    - exclude_keywords はいずれかを含む記事を除外。
    - max_age_days が None の場合は日付フィルタなし（既存動作を維持）。
      指定されている場合、now - published_parsed が max_age_days 日を超える
      記事を除外する。published_parsed が None（発行日パース不能）の場合は、
      リポジトリの一貫したエラーハンドリング方針（フィルタは例外を投げず
      静かに除外/素通りする）に従い、安全側に倒して除外せず素通りさせる。
    """
    if now is None:
        now = datetime.now(timezone.utc)

    result: list[Article] = []
    for article in articles:
        haystack = f"{article.title}\n{article.summary_source}"

        if filters.include_keywords:
            if not any(kw in haystack for kw in filters.include_keywords):
                continue

        if filters.exclude_keywords:
            if any(kw in haystack for kw in filters.exclude_keywords):
                continue

        if filters.max_age_days is not None and article.published_parsed is not None:
            if now - article.published_parsed > timedelta(days=filters.max_age_days):
                continue

        result.append(article)
    return result


def fetch_all(
    feeds: list[FeedConfig], global_filters: FiltersConfig, store: StateStore | None = None
) -> list[Article]:
    """有効な全フィードを取得し、フィード単位/グローバルのフィルタを適用して返す。

    source_type に応じて既存RSS取得(fetch_feed_entries)とscraper_fetcher.fetch_via_scraper
    にディスパッチする。store はscraper種別の健全性記録(source_health)にのみ使う。
    """
    all_articles: list[Article] = []
    for feed in feeds:
        if not feed.enabled:
            continue
        try:
            if feed.source_type == "scraper":
                articles = fetch_via_scraper(feed, store=store)
            else:
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
