"""スクレイパー（RSS/Atomがないサイト向け）による記事取得モジュール。

スクレイパは scrapers/{scraper_id}/scraper.py に配置し、
`fetch(options: dict, http: httpx.Client) -> list[dict]` という契約のみを守れば
よい疎結合設計。src.core.models.Article を直接importしない
（レイアウト崩れの被害をそのサイトに限定するため）。
list[dict] -> Article への変換はこのモジュールが担う。
"""

from __future__ import annotations

import importlib.util
import logging
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

import httpx

from src.config import FeedConfig
from src.core.models import Article
from src.core.state import StateStore

logger = logging.getLogger(__name__)

DEFAULT_SCRAPERS_DIR = Path("scrapers")


def _parse_published_at(published_at: str | None) -> datetime | None:
    """published_at（ISO 8601想定の生文字列）をUTC awareなdatetimeへのベストエフォート変換。

    スクレイパーが返す日付表記はサイトごとにまちまちなため、ISO 8601形式として
    解釈できない場合は例外を投げず None を返す（既存の安全側スルー仕様を維持）。
    """
    if not published_at:
        return None
    try:
        parsed = datetime.fromisoformat(published_at)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class ScraperContractError(RuntimeError):
    """スクレイパーの戻り値がfetch()契約に違反している場合に送出する。"""


def _load_scraper_module(scraper_id: str, scrapers_dir: Path) -> ModuleType:
    """scrapers/{scraper_id}/scraper.py を動的importする。存在しなければFileNotFoundError。"""
    scraper_path = scrapers_dir / scraper_id / "scraper.py"
    if not scraper_path.exists():
        raise FileNotFoundError(f"スクレイパーが見つかりません: {scraper_path}")

    spec = importlib.util.spec_from_file_location(
        f"scrapers.{scraper_id}.scraper", scraper_path
    )
    if spec is None or spec.loader is None:
        raise ScraperContractError(f"スクレイパーのロードに失敗しました: {scraper_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _validate_records(records: object) -> list[dict]:
    """fetch()の戻り値がlist[dict]（url/titleが非空）であることを検証する。"""
    if not isinstance(records, list):
        raise ScraperContractError(
            f"スクレイパーのfetch()はlistを返す必要があります: got {type(records)!r}"
        )
    for record in records:
        if not isinstance(record, dict):
            raise ScraperContractError(
                f"スクレイパーのfetch()の各要素はdictである必要があります: got {type(record)!r}"
            )
        if not record.get("url"):
            raise ScraperContractError("スクレイパーの戻り値に url が欠落しています")
        if not record.get("title"):
            raise ScraperContractError("スクレイパーの戻り値に title が欠落しています")
    return records


def _records_to_articles(records: list[dict], feed: FeedConfig) -> list[Article]:
    """list[dict] -> Article への変換。

    スクレイパー契約は日付の生文字列のみを返す。ISO 8601形式として解釈できれば
    published_parsedに変換し、RSS/Atomと同じ日付フィルタ（max_age_days）を
    適用できるようにする。解釈できない表記は既存どおりNoneとし、
    日付フィルタ側の「published_parsed is None は安全側で素通り」仕様に委ねる。
    """
    articles: list[Article] = []
    for record in records:
        published_at = record.get("published_at")
        articles.append(
            Article(
                url=record["url"],
                title=record["title"],
                feed_name=feed.name,
                category=record.get("category", feed.category),
                summary_source=record.get("summary_source", ""),
                published_at=published_at,
                published_parsed=_parse_published_at(published_at),
            )
        )
    return articles


def fetch_via_scraper(
    feed: FeedConfig,
    store: StateStore | None = None,
    scrapers_dir: Path = DEFAULT_SCRAPERS_DIR,
    http_client: httpx.Client | None = None,
) -> list[Article]:
    """1フィード（scraper種別）分の記事一覧をスクレイパー経由で取得する。

    スクレイパーのimport失敗・fetch()内部例外・戻り値の契約違反は、いずれも
    このフィードの取得失敗として握りつぶし空リストを返す（他フィードをブロックしない）。
    取得結果は store が与えられていれば source_health テーブルに記録する。
    """
    scraper_id = feed.scraper_id or feed.name

    owns_client = http_client is None
    client = http_client if http_client is not None else httpx.Client(timeout=15.0)
    try:
        module = _load_scraper_module(scraper_id, scrapers_dir)
        options = {"url": feed.url, "feed_name": feed.name, "category": feed.category}
        records = module.fetch(options, client)
        records = _validate_records(records)
        articles = _records_to_articles(records, feed)
    except Exception as exc:  # noqa: BLE001 - 1スクレイパーの失敗が他フィードをブロックしない
        logger.exception(
            "スクレイパー %s (フィード %s) の取得中にエラーが発生しました", scraper_id, feed.name
        )
        if store is not None:
            store.record_source_health(scraper_id, status="error", article_count=0, error=str(exc))
        return []
    finally:
        if owns_client:
            client.close()

    if not articles:
        logger.warning("スクレイパー %s (フィード %s) の取得結果が0件でした", scraper_id, feed.name)
        if store is not None:
            store.record_source_health(scraper_id, status="empty", article_count=0)
        return []

    if store is not None:
        store.record_source_health(scraper_id, status="ok", article_count=len(articles))
    return articles
