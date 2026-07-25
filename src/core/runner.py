"""1日1回の配信バッチのオーケストレーション。

MCPサーバー（手動実行ツール）とCLI（cronバッチ）の両方から
このモジュールの run_digest() を呼び出すことで、ロジックを共有する。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from src.config import AppConfig
from src.core.delivery import DeliveryError, deliver_digest, resolve_delivery_targets
from src.core.digest import build_digest, summarize_articles
from src.core.feed_fetcher import fetch_all
from src.core.dedup import filter_new_articles
from src.core.state import StateStore
from src.llm.base import LLMProvider

logger = logging.getLogger(__name__)


@dataclass
class RunResult:
    status: str  # "delivered" | "empty_notified" | "empty_skipped" | "failed"
    article_count: int = 0
    delivered_targets: list[str] = field(default_factory=list)
    carried_over_count: int = 0
    error: str | None = None


def run_digest(
    config: AppConfig,
    store: StateStore,
    llm_provider: LLMProvider,
) -> RunResult:
    """配信バッチ本体。

    1. 全フィードを取得しフィルタ適用
    2. URL基準で重複統合・既配信除外
    3. 新着記事をpending登録（冪等）
    4. LLM要約（失敗/コスト超過時は縮退配信フラグ）
    5. 配信件数上限・グルーピングを適用
    6. Webhook配信
    7. 配信成功後にのみ delivered_at を確定
    8. delivery_runs に実行結果を記録
    """
    run_id = store.start_run()
    try:
        raw_articles = fetch_all(config.feeds, config.filters)
        new_articles = filter_new_articles(raw_articles, store, config.retention.seen_ttl_days)

        for article in new_articles:
            store.register_pending(article.normalized_url(), article.title, article.feed_name)

        if not new_articles:
            if config.schedule.notify_on_empty:
                targets = resolve_delivery_targets(config.enabled_delivery_targets())
                empty_digest = build_digest([], config.digest)
                try:
                    delivered_targets = deliver_digest(targets, empty_digest)
                except DeliveryError as exc:
                    store.finish_run(run_id, "failed", 0, str(exc))
                    return RunResult(status="failed", article_count=0, error=str(exc))
                store.finish_run(run_id, "empty_notified", 0)
                return RunResult(
                    status="empty_notified", article_count=0, delivered_targets=delivered_targets
                )
            store.finish_run(run_id, "empty_skipped", 0)
            return RunResult(status="empty_skipped", article_count=0)

        summarize_articles(new_articles, llm_provider, config.llm)
        digest = build_digest(new_articles, config.digest)

        targets = resolve_delivery_targets(config.enabled_delivery_targets())
        try:
            delivered_targets = deliver_digest(targets, digest)
        except DeliveryError as exc:
            store.finish_run(run_id, "failed", len(digest.articles), str(exc))
            return RunResult(
                status="failed",
                article_count=len(digest.articles),
                error=str(exc),
                carried_over_count=digest.carried_over_count,
            )

        for article in digest.articles:
            store.mark_delivered(article.normalized_url())

        store.finish_run(run_id, "delivered", len(digest.articles))
        return RunResult(
            status="delivered",
            article_count=len(digest.articles),
            delivered_targets=delivered_targets,
            carried_over_count=digest.carried_over_count,
        )
    except Exception as exc:  # noqa: BLE001 - バッチ全体の予期しない失敗も記録する
        logger.exception("配信バッチ実行中に予期しないエラーが発生しました")
        store.finish_run(run_id, "failed", 0, str(exc))
        return RunResult(status="failed", article_count=0, error=str(exc))
