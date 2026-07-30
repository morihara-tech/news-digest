"""パーソナルニュースダイジェストのMCPサーバー。

設定管理・履歴参照・手動実行・フィードバック記録の4機能をMCPツールとして
提供する。バッチ実行ロジックは src/core 配下をCLI（src/cli.py）と共有する。
"""

from __future__ import annotations

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from src.config import load_config
from src.core.state import StateStore
from src.tools.config_tools import get_config_summary, list_feeds
from src.tools.feedback_tools import record_feedback
from src.tools.history_tools import get_delivery_history, get_seen_articles
from src.tools.run_tools import trigger_manual_run

load_dotenv()

mcp = FastMCP("news-digest")


@mcp.tool()
def get_config() -> dict:
    """現在のconfig.yamlの設定概要を返す（Webhook URL等の機微情報は含めない）。"""
    config = load_config()
    return get_config_summary(config)


@mcp.tool()
def list_registered_feeds() -> list[dict]:
    """登録されているフィード一覧（有効なフィルタ設定含む）を返す。"""
    config = load_config()
    return list_feeds(config)


@mcp.tool()
def get_run_history(limit: int = 20) -> list[dict]:
    """直近の配信バッチ実行履歴を返す。"""
    with StateStore() as store:
        return get_delivery_history(store, limit=limit)


@mcp.tool()
def get_recent_articles(limit: int = 100) -> list[dict]:
    """直近に検知した記事の既読/配信状態を返す。"""
    with StateStore() as store:
        return get_seen_articles(store, limit=limit)


@mcp.tool()
def run_digest_now() -> dict:
    """配信バッチを即時1回実行する（手動実行）。"""
    config = load_config()
    with StateStore() as store:
        return trigger_manual_run(config, store)


@mcp.tool()
def submit_feedback(url: str, feedback_type: str, value: str | None = None) -> dict:
    """記事に対するフィードバックを記録する。good/bad/mute（大文字小文字は無視）を受け付ける。"""
    with StateStore() as store:
        return record_feedback(store, url=url, feedback_type=feedback_type, value=value)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
