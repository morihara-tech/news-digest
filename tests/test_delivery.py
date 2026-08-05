from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from src.config import DeliveryTargetConfig, ScoringConfig
from src.core.delivery import (
    DeliveryError,
    DeliveryTarget,
    build_payload,
    deliver_digest,
    format_google_chat_payload,
    format_slack_payload,
    resolve_delivery_targets,
)
from src.core.digest import build_digest
from src.config import DigestConfig
from src.core.models import Article


def _digest_with_one_article(degraded: bool = False):
    article = Article(url="https://example.com/a", title="Title A", feed_name="feed")
    if degraded:
        article.degraded = True
    else:
        article.summary = "要約テキスト"
    return build_digest([article], DigestConfig(max_articles=10, group_by="feed"))


def test_format_slack_payload_empty_digest():
    digest = build_digest([], DigestConfig())
    payload = format_slack_payload(digest)
    assert "新着記事はありませんでした" in payload["text"]


def test_format_slack_payload_with_summary():
    digest = _digest_with_one_article(degraded=False)
    payload = format_slack_payload(digest)
    assert "Title A" in payload["text"]
    assert "要約テキスト" in payload["text"]


def test_format_slack_payload_degraded_article_has_no_summary_text():
    digest = _digest_with_one_article(degraded=True)
    payload = format_slack_payload(digest)
    assert "Title A" in payload["text"]
    assert "https://example.com/a" in payload["text"]


def test_format_google_chat_payload_empty_digest():
    digest = build_digest([], DigestConfig())
    payload = format_google_chat_payload(digest)
    assert "新着記事はありませんでした" in payload["text"]


def _digest_with_articles(articles: list[Article]):
    return build_digest(articles, DigestConfig(max_articles=10, group_by="feed"))


def test_format_slack_payload_emphasized_article_has_marker_prefix():
    article = Article(url="https://example.com/a", title="Title A", feed_name="feed")
    article.summary = "要約テキスト"
    article.emphasized = True
    digest = _digest_with_articles([article])
    scoring_config = ScoringConfig()

    payload = format_slack_payload(digest, scoring_config=scoring_config)
    assert f"{scoring_config.emphasis_marker}Title A" in payload["text"]


def test_format_slack_payload_non_emphasized_article_has_no_marker():
    article = Article(url="https://example.com/a", title="Title A", feed_name="feed")
    article.summary = "要約テキスト"
    article.emphasized = False
    digest = _digest_with_articles([article])
    scoring_config = ScoringConfig()

    payload = format_slack_payload(digest, scoring_config=scoring_config)
    assert scoring_config.emphasis_marker not in payload["text"]
    assert "Title A" in payload["text"]


def test_format_slack_payload_without_scoring_config_never_emphasizes():
    """scoring_config未指定の場合(後方互換)は、emphasized=Trueでもマークを付与しない。"""
    article = Article(url="https://example.com/a", title="Title A", feed_name="feed")
    article.summary = "要約テキスト"
    article.emphasized = True
    digest = _digest_with_articles([article])

    payload = format_slack_payload(digest)
    assert "⭐" not in payload["text"]
    assert "Title A" in payload["text"]


def test_format_slack_payload_muted_or_degraded_article_kept_and_not_emphasized():
    """ミュート・degraded記事はemphasized=False固定(scoring.py側の責務)であり、
    delivery層はarticle.emphasizedをそのまま見るだけでタイトル+リンクは維持される。"""
    article = Article(url="https://example.com/a", title="Title A", feed_name="feed")
    article.degraded = True
    article.emphasized = False
    digest = _digest_with_articles([article])
    scoring_config = ScoringConfig()

    payload = format_slack_payload(digest, scoring_config=scoring_config)
    assert scoring_config.emphasis_marker not in payload["text"]
    assert "Title A" in payload["text"]
    assert "https://example.com/a" in payload["text"]


def test_format_google_chat_payload_emphasized_article_has_marker_prefix():
    article = Article(url="https://example.com/a", title="Title A", feed_name="feed")
    article.summary = "要約テキスト"
    article.emphasized = True
    digest = _digest_with_articles([article])
    scoring_config = ScoringConfig()

    payload = format_google_chat_payload(digest, scoring_config=scoring_config)
    assert f"{scoring_config.emphasis_marker}Title A" in payload["text"]


def test_format_google_chat_payload_without_scoring_config_never_emphasizes():
    article = Article(url="https://example.com/a", title="Title A", feed_name="feed")
    article.summary = "要約テキスト"
    article.emphasized = True
    digest = _digest_with_articles([article])

    payload = format_google_chat_payload(digest)
    assert "⭐" not in payload["text"]
    assert "Title A" in payload["text"]


def test_format_google_chat_payload_degraded_article_kept_with_title_and_link():
    article = Article(url="https://example.com/a", title="Title A", feed_name="feed")
    article.degraded = True
    article.emphasized = False
    digest = _digest_with_articles([article])
    scoring_config = ScoringConfig()

    payload = format_google_chat_payload(digest, scoring_config=scoring_config)
    assert "Title A" in payload["text"]
    assert "https://example.com/a" in payload["text"]
    assert scoring_config.emphasis_marker not in payload["text"]


def test_format_slack_payload_uses_bullet_dot_not_asterisk():
    digest = _digest_with_one_article(degraded=False)
    payload = format_slack_payload(digest)
    assert "• <https://example.com/a|Title A>" in payload["text"]
    assert "* <https://example.com/a|Title A>" not in payload["text"]


def test_format_slack_payload_appends_inline_code_date():
    article = Article(url="https://example.com/a", title="Title A", feed_name="feed")
    article.summary = "要約テキスト"
    article.published_parsed = datetime(2026, 8, 5, tzinfo=timezone.utc)
    digest = _digest_with_articles([article])

    payload = format_slack_payload(digest)
    assert "`08/05`" in payload["text"]


def test_format_slack_payload_omits_date_when_published_parsed_missing():
    article = Article(url="https://example.com/a", title="Title A", feed_name="feed")
    article.summary = "要約テキスト"
    article.published_parsed = None
    digest = _digest_with_articles([article])

    payload = format_slack_payload(digest)
    # 日付のインラインコード（`MM/DD`形式）が付与されないことのみ確認する
    assert "`08" not in payload["text"]
    assert "`0" not in payload["text"]


def test_format_slack_payload_summary_wrapped_in_code_block_title_line_not():
    article = Article(url="https://example.com/a", title="Title A", feed_name="feed")
    article.summary = "要約テキスト"
    article.published_parsed = datetime(2026, 8, 5, tzinfo=timezone.utc)
    digest = _digest_with_articles([article])

    payload = format_slack_payload(digest)
    text = payload["text"]
    lines = text.split("\n")
    title_line = next(line for line in lines if "<https://example.com/a|Title A>" in line)
    # タイトル行自体はコードブロック記号を含まない
    assert "```" not in title_line
    # 要約はコードブロックで囲まれている
    assert "```\n要約テキスト\n```" in text


def test_format_slack_payload_degraded_article_has_no_empty_code_block():
    digest = _digest_with_one_article(degraded=True)
    payload = format_slack_payload(digest)
    assert "```" not in payload["text"]


def test_format_google_chat_payload_matches_slack_style_format():
    """Google Chatも共通フォーマット（箇条書き記号・日付インラインコード・要約コードブロック）を使う。"""
    article = Article(url="https://example.com/a", title="Title A", feed_name="feed")
    article.summary = "要約テキスト"
    article.published_parsed = datetime(2026, 8, 5, tzinfo=timezone.utc)
    digest = _digest_with_articles([article])

    payload = format_google_chat_payload(digest)
    text = payload["text"]
    assert "• <https://example.com/a|Title A> `08/05`" in text
    assert "```\n要約テキスト\n```" in text

    lines = text.split("\n")
    title_line = next(line for line in lines if "<https://example.com/a|Title A>" in line)
    assert "```" not in title_line


def test_resolve_delivery_targets_reads_env(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example.com/slack")
    configs = [
        DeliveryTargetConfig(
            name="my-slack", format="slack", webhook_url_env="SLACK_WEBHOOK_URL", enabled=True
        )
    ]
    targets = resolve_delivery_targets(configs)
    assert len(targets) == 1
    assert targets[0].webhook_url == "https://hooks.example.com/slack"


def test_resolve_delivery_targets_skips_missing_env(monkeypatch):
    monkeypatch.delenv("UNSET_WEBHOOK_URL", raising=False)
    configs = [
        DeliveryTargetConfig(
            name="my-slack", format="slack", webhook_url_env="UNSET_WEBHOOK_URL", enabled=True
        )
    ]
    targets = resolve_delivery_targets(configs)
    assert targets == []


def test_deliver_digest_success(monkeypatch):
    digest = _digest_with_one_article()
    target = DeliveryTarget(
        config=DeliveryTargetConfig(
            name="my-slack", format="slack", webhook_url_env="SLACK_WEBHOOK_URL"
        ),
        webhook_url="https://hooks.example.com/slack",
    )

    class FakeResponse:
        def raise_for_status(self):
            return None

    def fake_post(url, json, timeout):
        return FakeResponse()

    monkeypatch.setattr(httpx, "post", fake_post)
    succeeded = deliver_digest([target], digest)
    assert succeeded == ["my-slack"]


def test_deliver_digest_raises_when_all_fail(monkeypatch):
    digest = _digest_with_one_article()
    target = DeliveryTarget(
        config=DeliveryTargetConfig(
            name="my-slack", format="slack", webhook_url_env="SLACK_WEBHOOK_URL"
        ),
        webhook_url="https://hooks.example.com/slack",
    )

    def fake_post(url, json, timeout):
        raise httpx.ConnectError("connection failed", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    with pytest.raises(DeliveryError):
        deliver_digest([target], digest)
