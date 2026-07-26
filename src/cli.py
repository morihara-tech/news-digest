"""cronから叩くCLIエントリポイント。

`uv run news-digest --config config.yaml --db state/digest.db run` のように
グローバルオプションの後にサブコマンドを指定して実行する。
MCPサーバー(src/server.py)と同じ src/core のロジックを共有する。
"""

from __future__ import annotations

import argparse
import logging
import sys

from dotenv import load_dotenv

from src.config import load_config
from src.core.runner import run_digest
from src.core.state import StateStore
from src.llm.factory import create_llm_provider

load_dotenv()

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


def cmd_run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    with StateStore(args.db) as store:
        llm_provider = create_llm_provider(config.llm)
        result = run_digest(config, store, llm_provider)

    logger.info(
        "配信バッチ完了: status=%s article_count=%s carried_over=%s",
        result.status,
        result.article_count,
        result.carried_over_count,
    )
    if result.error:
        logger.error("エラー: %s", result.error)
        return 1
    return 0


def cmd_scrapers_check(args: argparse.Namespace) -> int:
    with StateStore(args.db) as store:
        rows = store.get_latest_source_health()

    if not rows:
        print("source_health レコードがありません（scraper種別のフィードが未実行、または未設定です）")
        return 0

    has_issue = False
    header = f"{'scraper_id':<24}{'checked_at':<28}{'status':<8}{'count':<7}error"
    print(header)
    print("-" * len(header))
    for row in rows:
        if row["status"] != "ok":
            has_issue = True
        print(
            f"{row['scraper_id']:<24}{row['checked_at']:<28}{row['status']:<8}"
            f"{row['article_count']:<7}{row['error'] or ''}"
        )
    return 1 if has_issue else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="news-digest")
    parser.add_argument(
        "--config", default="config.yaml", help="設定ファイルのパス（既定: config.yaml）"
    )
    parser.add_argument(
        "--db", default="state/digest.db", help="sqlite3状態DBのパス（既定: state/digest.db）"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="配信バッチを1回実行する")
    run_parser.set_defaults(func=cmd_run)

    scrapers_parser = subparsers.add_parser("scrapers", help="スクレイパー関連コマンド")
    scrapers_subparsers = scrapers_parser.add_subparsers(
        dest="scrapers_command", required=True
    )
    check_parser = scrapers_subparsers.add_parser("check", help="source_healthの状態を確認する")
    check_parser.set_defaults(func=cmd_scrapers_check)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    exit_code = args.func(args)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
