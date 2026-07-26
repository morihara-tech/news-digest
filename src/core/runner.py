"""1日1回の配信バッチのオーケストレーション。

MCPサーバー（手動実行ツール）とCLI（cronバッチ）の両方から
このモジュールの run_digest() を呼び出すことで、ロジックを共有する。

重複統合・既配信除外・配信件数上限（Phase 1）はサイト横断（グローバル）で
1回だけ実行し、その後は取得したサイト（フィード）ごとに要約・配信を独立して
行う（Phase 2）。1サイトの要約・配信失敗が他サイトの処理をブロックしない
（障害分離）ための構成になっている。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from src.config import AppConfig
from src.core.delivery import DeliveryError, deliver_digest, resolve_delivery_targets
from src.core.digest import build_digest, mark_cost_overflow, summarize_articles
from src.core.feed_fetcher import fetch_all
from src.core.dedup import filter_new_articles
from src.core.models import Article
from src.core.state import StateStore
from src.llm.base import LLMProvider

logger = logging.getLogger(__name__)


@dataclass
class SiteRunResult:
    """サイト（フィード）1件分の処理結果。"""

    feed_name: str
    status: str  # "delivered" | "failed"
    article_count: int = 0
    delivered_targets: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class RunResult:
    status: str  # "delivered" | "empty_notified" | "empty_skipped" | "no_delivery_target" | "failed"
    article_count: int = 0
    delivered_targets: list[str] = field(default_factory=list)
    carried_over_count: int = 0
    error: str | None = None
    site_results: list[SiteRunResult] = field(default_factory=list)


def _group_by_feed_name(articles: list[Article]) -> dict[str, list[Article]]:
    """記事群をfeed_name基準でグルーピングする（出現順を保持）。

    build_digest() 内部の groups（digest_config.group_by に従うグルーピング）
    とは別物。サイト分割は常にfeed_name基準で行う（サイト=フィードという設計
    のため、group_by設定の値に関わらず常にfeed_name分割する）。
    """
    groups: dict[str, list[Article]] = {}
    for article in articles:
        groups.setdefault(article.feed_name, []).append(article)
    return groups


def run_digest(
    config: AppConfig,
    store: StateStore,
    llm_provider: LLMProvider,
) -> RunResult:
    """配信バッチ本体。

    Phase 1（グローバル、1回だけ）:
      1. 全フィードを取得しフィルタ適用
      2. URL基準で重複統合・既配信除外
      3. 新着記事をpending登録（冪等）
      4. 配信件数上限を適用（サイト分割より前）
      5. コスト上限による縮退配信マーキング（サイト横断で1回）
      6. 配信先解決

    Phase 2（サイトごと、各サイト独立）:
      1. サイトごとにLLM要約
      2. サイトごとに件数上限・グルーピングを適用したダイジェストを組み立て
      3. サイトごとに独立したメッセージとしてWebhook配信
      4. 配信成功後にのみそのサイトの記事の delivered_at を確定
      5. 1サイトの失敗（要約・配信とも）は他サイトの処理をブロックしない

    最後に delivery_runs に実行結果を記録する。
    """
    run_id = store.start_run()
    try:
        raw_articles = fetch_all(config.feeds, config.filters, store)
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

        global_digest = build_digest(new_articles, config.digest)
        mark_cost_overflow(global_digest.articles, config.llm.max_articles_to_summarize)

        targets = resolve_delivery_targets(config.enabled_delivery_targets())
        if not targets:
            error_message = "有効な配信先が解決できませんでした（環境変数未設定等）"
            logger.warning(
                "配信先が解決できず配信をスキップしました: article_count=%s",
                len(global_digest.articles),
            )
            store.finish_run(
                run_id, "no_delivery_target", len(global_digest.articles), error_message
            )
            return RunResult(
                status="no_delivery_target",
                article_count=len(global_digest.articles),
                error=error_message,
                carried_over_count=global_digest.carried_over_count,
            )

        site_groups = _group_by_feed_name(global_digest.articles)
        site_results: list[SiteRunResult] = []

        for feed_name, site_articles in site_groups.items():
            try:
                summarize_articles(site_articles, llm_provider)
                site_digest = build_digest(site_articles, config.digest)

                try:
                    delivered_targets = deliver_digest(targets, site_digest, site_label=feed_name)
                except DeliveryError as exc:
                    logger.error("サイト %s の配信に失敗しました: %s", feed_name, exc)
                    site_results.append(
                        SiteRunResult(
                            feed_name=feed_name,
                            status="failed",
                            article_count=len(site_articles),
                            error=str(exc),
                        )
                    )
                    continue

                for article in site_digest.articles:
                    store.mark_delivered(article.normalized_url())

                site_results.append(
                    SiteRunResult(
                        feed_name=feed_name,
                        status="delivered",
                        article_count=len(site_articles),
                        delivered_targets=delivered_targets,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - 1サイトの想定外失敗が他サイトをブロックしない
                logger.exception("サイト %s の処理中に予期しないエラーが発生しました", feed_name)
                site_results.append(
                    SiteRunResult(
                        feed_name=feed_name,
                        status="failed",
                        article_count=len(site_articles),
                        error=str(exc),
                    )
                )

        succeeded_sites = [r for r in site_results if r.status == "delivered"]
        overall_status = "delivered" if succeeded_sites else "failed"
        article_count = len(global_digest.articles)
        delivered_targets_union = sorted(
            {name for r in succeeded_sites for name in r.delivered_targets}
        )
        overall_error = (
            None
            if succeeded_sites
            else "; ".join(f"{r.feed_name}: {r.error}" for r in site_results if r.error)
        )

        store.finish_run(run_id, overall_status, article_count, overall_error)
        return RunResult(
            status=overall_status,
            article_count=article_count,
            delivered_targets=delivered_targets_union,
            carried_over_count=global_digest.carried_over_count,
            error=overall_error,
            site_results=site_results,
        )
    except Exception as exc:  # noqa: BLE001 - バッチ全体の予期しない失敗も記録する
        logger.exception("配信バッチ実行中に予期しないエラーが発生しました")
        store.finish_run(run_id, "failed", 0, str(exc))
        return RunResult(status="failed", article_count=0, error=str(exc))
