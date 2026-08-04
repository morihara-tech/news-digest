from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.config import FeedConfig
from src.core.scraper_fetcher import fetch_via_scraper
from src.core.state import StateStore

SCRAPERS_DIR = Path(__file__).parent.parent / "scrapers"


class FakeResponse:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self) -> None:
        return None


class FakeHttpClient:
    """options["url"]に関わらずfixtureのHTMLを返す疑似httpx.Client。"""

    def __init__(self, html: str):
        self._html = html

    def get(self, url: str) -> FakeResponse:
        return FakeResponse(self._html)


def test_fetch_via_scraper_success_matches_expected_json(tmp_path):
    scraper_dir = SCRAPERS_DIR / "example-blog"
    html = (scraper_dir / "sample.html").read_text(encoding="utf-8")
    expected = json.loads((scraper_dir / "expected.json").read_text(encoding="utf-8"))

    feed = FeedConfig(
        name="Example Blog",
        url="https://example.com/blog",
        category="tech",
        source_type="scraper",
        scraper_id="example-blog",
    )

    with StateStore(tmp_path / "digest.db") as store:
        articles = fetch_via_scraper(
            feed,
            store=store,
            scrapers_dir=SCRAPERS_DIR,
            http_client=FakeHttpClient(html),
        )

        assert len(articles) == len(expected)
        for article, record in zip(articles, expected):
            assert article.url == record["url"]
            assert article.title == record["title"]
            assert article.summary_source == record["summary_source"]
            assert article.published_at == record["published_at"]
            assert article.feed_name == "Example Blog"
            assert article.category == "tech"
            assert article.published_parsed == datetime.fromisoformat(
                record["published_at"]
            ).astimezone(timezone.utc)

        rows = store.get_latest_source_health()
        assert len(rows) == 1
        assert rows[0]["scraper_id"] == "example-blog"
        assert rows[0]["status"] == "ok"
        assert rows[0]["article_count"] == len(expected)


def test_fetch_via_scraper_parses_iso_published_at_and_falls_back_to_none(tmp_path):
    scrapers_dir = tmp_path / "scrapers"
    _write_dummy_scraper(
        scrapers_dir,
        "mixed-dates",
        "def fetch(options, http):\n"
        "    return [\n"
        '        {"url": "https://example.com/a", "title": "ISO日付", "published_at": "2026-04-03"},\n'
        '        {"url": "https://example.com/b", "title": "パース不能な日付", "published_at": "2026年4月3日"},\n'
        "    ]\n",
    )

    feed = FeedConfig(
        name="Mixed Dates",
        url="https://example.com/mixed",
        source_type="scraper",
        scraper_id="mixed-dates",
    )

    with StateStore(tmp_path / "digest.db") as store:
        articles = fetch_via_scraper(
            feed, store=store, scrapers_dir=scrapers_dir, http_client=FakeHttpClient("<html></html>")
        )
        assert articles[0].published_parsed == datetime(2026, 4, 3, tzinfo=timezone.utc)
        assert articles[1].published_parsed is None


def _write_dummy_scraper(scrapers_dir: Path, scraper_id: str, body: str) -> None:
    scraper_dir = scrapers_dir / scraper_id
    scraper_dir.mkdir(parents=True, exist_ok=True)
    (scraper_dir / "scraper.py").write_text(body, encoding="utf-8")


def test_fetch_via_scraper_contract_violation_is_swallowed(tmp_path):
    scrapers_dir = tmp_path / "scrapers"
    _write_dummy_scraper(
        scrapers_dir,
        "bad-scraper",
        'def fetch(options, http):\n    return [{"title": "url欠落"}]\n',
    )

    feed = FeedConfig(
        name="Bad Blog",
        url="https://example.com/bad",
        source_type="scraper",
        scraper_id="bad-scraper",
    )

    with StateStore(tmp_path / "digest.db") as store:
        articles = fetch_via_scraper(
            feed, store=store, scrapers_dir=scrapers_dir, http_client=FakeHttpClient("<html></html>")
        )
        assert articles == []

        rows = store.get_latest_source_health()
        assert len(rows) == 1
        assert rows[0]["scraper_id"] == "bad-scraper"
        assert rows[0]["status"] == "error"
        assert rows[0]["error"] is not None


def test_fetch_via_scraper_non_list_return_is_contract_error(tmp_path):
    scrapers_dir = tmp_path / "scrapers"
    _write_dummy_scraper(
        scrapers_dir,
        "not-a-list",
        'def fetch(options, http):\n    return {"not": "a list"}\n',
    )

    feed = FeedConfig(
        name="Not A List",
        url="https://example.com/x",
        source_type="scraper",
        scraper_id="not-a-list",
    )

    with StateStore(tmp_path / "digest.db") as store:
        articles = fetch_via_scraper(
            feed, store=store, scrapers_dir=scrapers_dir, http_client=FakeHttpClient("<html></html>")
        )
        assert articles == []
        rows = store.get_latest_source_health()
        assert rows[0]["status"] == "error"


def test_fetch_via_scraper_empty_result_records_empty_status(tmp_path):
    scrapers_dir = tmp_path / "scrapers"
    _write_dummy_scraper(
        scrapers_dir,
        "empty-scraper",
        "def fetch(options, http):\n    return []\n",
    )

    feed = FeedConfig(
        name="Empty Blog",
        url="https://example.com/empty",
        source_type="scraper",
        scraper_id="empty-scraper",
    )

    with StateStore(tmp_path / "digest.db") as store:
        articles = fetch_via_scraper(
            feed, store=store, scrapers_dir=scrapers_dir, http_client=FakeHttpClient("<html></html>")
        )
        assert articles == []
        rows = store.get_latest_source_health()
        assert rows[0]["status"] == "empty"
        assert rows[0]["article_count"] == 0


def test_fetch_via_scraper_missing_scraper_module_is_swallowed(tmp_path):
    scrapers_dir = tmp_path / "scrapers"  # scraper_idに対応するディレクトリを作らない
    scrapers_dir.mkdir(parents=True, exist_ok=True)

    feed = FeedConfig(
        name="Nonexistent",
        url="https://example.com/nowhere",
        source_type="scraper",
        scraper_id="nonexistent-scraper",
    )

    with StateStore(tmp_path / "digest.db") as store:
        articles = fetch_via_scraper(
            feed, store=store, scrapers_dir=scrapers_dir, http_client=FakeHttpClient("<html></html>")
        )
        assert articles == []
        rows = store.get_latest_source_health()
        assert rows[0]["scraper_id"] == "nonexistent-scraper"
        assert rows[0]["status"] == "error"


def test_fetch_via_scraper_without_store_does_not_raise(tmp_path):
    scrapers_dir = tmp_path / "scrapers"
    _write_dummy_scraper(
        scrapers_dir,
        "no-store-scraper",
        "def fetch(options, http):\n    return []\n",
    )
    feed = FeedConfig(
        name="No Store",
        url="https://example.com/x",
        source_type="scraper",
        scraper_id="no-store-scraper",
    )
    articles = fetch_via_scraper(
        feed, store=None, scrapers_dir=scrapers_dir, http_client=FakeHttpClient("<html></html>")
    )
    assert articles == []
