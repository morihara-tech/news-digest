from __future__ import annotations

import httpx

from src.config import (
    AppConfig,
    DeliveryTargetConfig,
    DigestConfig,
    FeedConfig,
    LLMConfig,
    RetentionConfig,
    ScheduleConfig,
)
from src.core.runner import run_digest
from src.core.state import StateStore
from tests.mock_llm_provider import MockLLMProvider


def _config_with_feed(fixtures_dir, **overrides) -> AppConfig:
    feed_url = str(fixtures_dir / "rss_tech.xml")
    return AppConfig(
        llm=LLMConfig(),
        delivery=[
            DeliveryTargetConfig(
                name="my-slack",
                format="slack",
                webhook_url_env="SLACK_WEBHOOK_URL",
                enabled=True,
            )
        ],
        schedule=ScheduleConfig(notify_on_empty=True),
        digest=overrides.get("digest", DigestConfig(max_articles=20, group_by="feed")),
        retention=RetentionConfig(seen_ttl_days=90),
        feeds=[FeedConfig(name="Tech", url=feed_url, category="tech")],
    )


def test_run_digest_delivers_new_articles(tmp_path, fixtures_dir, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example.com/slack")

    class FakeResponse:
        def raise_for_status(self):
            return None

    monkeypatch.setattr(httpx, "post", lambda url, json, timeout: FakeResponse())

    config = _config_with_feed(fixtures_dir)
    with StateStore(tmp_path / "digest.db") as store:
        provider = MockLLMProvider()
        result = run_digest(config, store, provider)

        assert result.status == "delivered"
        assert result.article_count == 3
        assert result.delivered_targets == ["my-slack"]

        # 配信成功後にのみdelivered_atが確定していることを確認
        rows = store.get_seen_articles()
        assert len(rows) == 3
        assert all(row["delivered_at"] is not None for row in rows)


def test_run_digest_second_run_skips_already_delivered(tmp_path, fixtures_dir, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example.com/slack")

    class FakeResponse:
        def raise_for_status(self):
            return None

    monkeypatch.setattr(httpx, "post", lambda url, json, timeout: FakeResponse())

    config = _config_with_feed(fixtures_dir)
    with StateStore(tmp_path / "digest.db") as store:
        provider = MockLLMProvider()
        first = run_digest(config, store, provider)
        assert first.status == "delivered"

        second = run_digest(config, store, provider)
        assert second.status == "empty_notified"
        assert second.article_count == 0


def test_run_digest_notifies_on_empty(tmp_path, fixtures_dir, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example.com/slack")

    sent_payloads = []

    class FakeResponse:
        def raise_for_status(self):
            return None

    def fake_post(url, json, timeout):
        sent_payloads.append(json)
        return FakeResponse()

    monkeypatch.setattr(httpx, "post", fake_post)

    config = _config_with_feed(fixtures_dir)
    config.feeds = []  # フィードなし = 常に0件

    with StateStore(tmp_path / "digest.db") as store:
        provider = MockLLMProvider()
        result = run_digest(config, store, provider)
        assert result.status == "empty_notified"
        assert len(sent_payloads) == 1
        assert "新着記事はありませんでした" in sent_payloads[0]["text"]


def test_run_digest_skips_notification_when_disabled(tmp_path, fixtures_dir, monkeypatch):
    config = _config_with_feed(fixtures_dir)
    config.feeds = []
    config.schedule.notify_on_empty = False

    called = []
    monkeypatch.setattr(httpx, "post", lambda *a, **k: called.append(1))

    with StateStore(tmp_path / "digest.db") as store:
        provider = MockLLMProvider()
        result = run_digest(config, store, provider)
        assert result.status == "empty_skipped"
        assert called == []


def test_run_digest_respects_max_articles_and_carries_over(tmp_path, fixtures_dir, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example.com/slack")

    class FakeResponse:
        def raise_for_status(self):
            return None

    monkeypatch.setattr(httpx, "post", lambda url, json, timeout: FakeResponse())

    config = _config_with_feed(fixtures_dir, digest=DigestConfig(max_articles=1, group_by="feed"))
    with StateStore(tmp_path / "digest.db") as store:
        provider = MockLLMProvider()
        result = run_digest(config, store, provider)
        assert result.status == "delivered"
        assert result.article_count == 1
        assert result.carried_over_count == 2

        # 配信対象外だった記事はpendingのまま(delivered_at未設定)であり、
        # 次回実行時に再度新着として扱われる(=持ち越し)
        rows = {row["url"]: row for row in store.get_seen_articles()}
        delivered_count = sum(1 for row in rows.values() if row["delivered_at"] is not None)
        pending_count = sum(1 for row in rows.values() if row["delivered_at"] is None)
        assert delivered_count == 1
        assert pending_count == 2
