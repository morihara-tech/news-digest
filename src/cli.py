"""cronから叩くCLIエントリポイント。

`uv run news-digest run` のようにサブコマンドで実行する。
MCPサーバー(src/server.py)と同じ src/core のロジックを共有する。
"""

from __future__ import annotations

import argparse
import logging
import sys

from src.config import load_config
from src.core.runner import run_digest
from src.core.state import StateStore
from src.llm.factory import create_llm_provider

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

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    exit_code = args.func(args)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
