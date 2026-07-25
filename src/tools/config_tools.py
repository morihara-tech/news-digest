"""設定管理系のMCPツールで使う純粋関数群。"""

from __future__ import annotations

from src.config import AppConfig


def get_config_summary(config: AppConfig) -> dict:
    """現在のconfigの概要を返す（Webhook URL等の機微情報は含めない）。"""
    return {
        "llm_provider": config.llm.provider,
        "llm_model": config.llm.model,
        "digest_max_articles": config.digest.max_articles,
        "schedule_times": config.schedule.times,
        "notify_on_empty": config.schedule.notify_on_empty,
        "seen_ttl_days": config.retention.seen_ttl_days,
        "delivery_targets": [
            {"name": d.name, "format": d.format, "enabled": d.enabled} for d in config.delivery
        ],
        "feed_count": len(config.feeds),
        "enabled_feed_count": len(config.enabled_feeds()),
    }


def list_feeds(config: AppConfig) -> list[dict]:
    """フィード一覧を返す。"""
    result = []
    for feed in config.feeds:
        effective = feed.effective_filters(config.filters)
        result.append(
            {
                "name": feed.name,
                "url": feed.url,
                "category": feed.category,
                "enabled": feed.enabled,
                "include_keywords": effective.include_keywords,
                "exclude_keywords": effective.exclude_keywords,
            }
        )
    return result
