"""Slack / Google Chat Incoming Webhookへの配信。"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from src.config import DeliveryTargetConfig, ScoringConfig, get_env
from src.core.digest import DigestResult
from src.core.models import Article

logger = logging.getLogger(__name__)

EMPTY_DIGEST_MESSAGE = "本日は新着記事はありませんでした。"


class DeliveryError(RuntimeError):
    """Webhook配信失敗時に送出する。"""


@dataclass
class DeliveryTarget:
    config: DeliveryTargetConfig
    webhook_url: str


def resolve_delivery_targets(configs: list[DeliveryTargetConfig]) -> list[DeliveryTarget]:
    """有効な配信先について .env からWebhook URLを解決する。

    環境変数が未設定の配信先はスキップする（ログ出力のみ）。
    """
    targets: list[DeliveryTarget] = []
    for config in configs:
        if not config.enabled:
            continue
        url = get_env(config.webhook_url_env)
        if not url:
            logger.warning(
                "配信先 %s の環境変数 %s が未設定のためスキップします",
                config.name,
                config.webhook_url_env,
            )
            continue
        targets.append(DeliveryTarget(config=config, webhook_url=url))
    return targets


def _emphasized_title(article: Article, scoring_config: ScoringConfig | None) -> str:
    """強調対象記事のタイトルに絵文字マーカーを前置する。

    scoring_config が未指定の場合は後方互換のため何も付与しない。
    ミュート・degraded記事は article.emphasized が scoring.py 側で
    既に False に倒れているため、ここでは article.emphasized をそのまま見るだけでよい。
    """
    if scoring_config is not None and article.emphasized:
        return f"{scoring_config.emphasis_marker}{article.title}"
    return article.title


def _group_heading(group_name: str, scoring_config: ScoringConfig | None) -> str:
    """グループ見出し。scoring有効時は「重要度順」であることを明示する。"""
    if scoring_config is not None and scoring_config.enabled:
        return f"{group_name}（重要度順）"
    return group_name


def _format_article_line(article: Article, scoring_config: ScoringConfig | None = None) -> str:
    title = _emphasized_title(article, scoring_config)
    if article.degraded or not article.summary:
        return f"* <{article.url}|{title}>"
    return f"* <{article.url}|{title}>\n  {article.summary}"


def format_slack_payload(
    digest: DigestResult,
    site_label: str | None = None,
    scoring_config: ScoringConfig | None = None,
) -> dict:
    if not digest.articles:
        return {"text": EMPTY_DIGEST_MESSAGE}

    lines: list[str] = []
    if site_label:
        lines.append(f"📰 *{site_label}*")
        lines.append("---")
    for group_name, articles in digest.groups.items():
        lines.append(f"*{_group_heading(group_name, scoring_config)}*")
        for article in articles:
            lines.append(_format_article_line(article, scoring_config))
    text = "\n".join(lines)
    return {"text": text}


def format_google_chat_payload(
    digest: DigestResult,
    site_label: str | None = None,
    scoring_config: ScoringConfig | None = None,
) -> dict:
    if not digest.articles:
        return {"text": EMPTY_DIGEST_MESSAGE}

    lines: list[str] = []
    if site_label:
        lines.append(f"📰 {site_label}")
        lines.append("---")
    for group_name, articles in digest.groups.items():
        lines.append(f"*{_group_heading(group_name, scoring_config)}*")
        for article in articles:
            title = _emphasized_title(article, scoring_config)
            if article.degraded or not article.summary:
                lines.append(f"- {title}\n  {article.url}")
            else:
                lines.append(f"- {title}\n  {article.summary}\n  {article.url}")
    text = "\n".join(lines)
    return {"text": text}


def build_payload(
    target: DeliveryTarget,
    digest: DigestResult,
    site_label: str | None = None,
    scoring_config: ScoringConfig | None = None,
) -> dict:
    if target.config.format == "slack":
        return format_slack_payload(digest, site_label=site_label, scoring_config=scoring_config)
    if target.config.format == "google_chat":
        return format_google_chat_payload(
            digest, site_label=site_label, scoring_config=scoring_config
        )
    raise ValueError(f"未知の配信フォーマットです: {target.config.format}")


def send_webhook(target: DeliveryTarget, payload: dict, timeout: float = 15.0) -> None:
    try:
        response = httpx.post(target.webhook_url, json=payload, timeout=timeout)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise DeliveryError(f"配信先 {target.config.name} への配信に失敗しました: {exc}") from exc


def deliver_digest(
    targets: list[DeliveryTarget],
    digest: DigestResult,
    site_label: str | None = None,
    scoring_config: ScoringConfig | None = None,
) -> list[str]:
    """全配信先に送信する。成功した配信先名のリストを返す。

    一部配信先が失敗しても他の配信先への送信は継続する。
    1件も成功しなかった場合は DeliveryError を送出する。

    site_label を指定すると、サイト（フィード）ごとの独立配信としてメッセージ
    本文の先頭にサイト名の見出しを付与する。
    scoring_config を指定すると、article.emphasized な記事のタイトル前に
    emphasis_marker を付与する（未指定・scoring.enabled=False時は付与しない）。
    """
    succeeded: list[str] = []
    errors: list[str] = []
    for target in targets:
        payload = build_payload(target, digest, site_label=site_label, scoring_config=scoring_config)
        try:
            send_webhook(target, payload)
            succeeded.append(target.config.name)
        except DeliveryError as exc:
            errors.append(str(exc))
            logger.error(str(exc))

    if not succeeded and targets:
        raise DeliveryError(f"すべての配信先への配信に失敗しました: {'; '.join(errors)}")

    return succeeded
