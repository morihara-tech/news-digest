"""Slack / Google Chat Incoming Webhookへの配信。"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from src.config import DeliveryTargetConfig, get_env
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


def _format_article_line(article: Article) -> str:
    if article.degraded or not article.summary:
        return f"* <{article.url}|{article.title}>"
    return f"* <{article.url}|{article.title}>\n  {article.summary}"


def format_slack_payload(digest: DigestResult, site_label: str | None = None) -> dict:
    if not digest.articles:
        return {"text": EMPTY_DIGEST_MESSAGE}

    lines: list[str] = []
    if site_label:
        lines.append(f"📰 *{site_label}*")
        lines.append("---")
    for group_name, articles in digest.groups.items():
        lines.append(f"*{group_name}*")
        for article in articles:
            lines.append(_format_article_line(article))
    text = "\n".join(lines)
    return {"text": text}


def format_google_chat_payload(digest: DigestResult, site_label: str | None = None) -> dict:
    if not digest.articles:
        return {"text": EMPTY_DIGEST_MESSAGE}

    lines: list[str] = []
    if site_label:
        lines.append(f"📰 {site_label}")
        lines.append("---")
    for group_name, articles in digest.groups.items():
        lines.append(f"*{group_name}*")
        for article in articles:
            if article.degraded or not article.summary:
                lines.append(f"- {article.title}\n  {article.url}")
            else:
                lines.append(f"- {article.title}\n  {article.summary}\n  {article.url}")
    text = "\n".join(lines)
    return {"text": text}


def build_payload(
    target: DeliveryTarget, digest: DigestResult, site_label: str | None = None
) -> dict:
    if target.config.format == "slack":
        return format_slack_payload(digest, site_label=site_label)
    if target.config.format == "google_chat":
        return format_google_chat_payload(digest, site_label=site_label)
    raise ValueError(f"未知の配信フォーマットです: {target.config.format}")


def send_webhook(target: DeliveryTarget, payload: dict, timeout: float = 15.0) -> None:
    try:
        response = httpx.post(target.webhook_url, json=payload, timeout=timeout)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise DeliveryError(f"配信先 {target.config.name} への配信に失敗しました: {exc}") from exc


def deliver_digest(
    targets: list[DeliveryTarget], digest: DigestResult, site_label: str | None = None
) -> list[str]:
    """全配信先に送信する。成功した配信先名のリストを返す。

    一部配信先が失敗しても他の配信先への送信は継続する。
    1件も成功しなかった場合は DeliveryError を送出する。

    site_label を指定すると、サイト（フィード）ごとの独立配信としてメッセージ
    本文の先頭にサイト名の見出しを付与する。
    """
    succeeded: list[str] = []
    errors: list[str] = []
    for target in targets:
        payload = build_payload(target, digest, site_label=site_label)
        try:
            send_webhook(target, payload)
            succeeded.append(target.config.name)
        except DeliveryError as exc:
            errors.append(str(exc))
            logger.error(str(exc))

    if not succeeded and targets:
        raise DeliveryError(f"すべての配信先への配信に失敗しました: {'; '.join(errors)}")

    return succeeded
