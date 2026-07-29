"""cronから叩くCLIエントリポイント。

`uv run news-digest --config config.yaml --db state/digest.db run` のように
グローバルオプションの後にサブコマンドを指定して実行する。
MCPサーバー(src/server.py)と同じ src/core のロジックを共有する。
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.config import AppConfig, load_config
from src.core.runner import run_digest
from src.core.state import StateStore
from src.llm.factory import create_llm_provider
from src.scheduler.base import (
    WRAPPER_SCRIPT_RELATIVE_PATH,
    SchedulerBackend,
    warn_if_timezone_mismatch,
    write_wrapper_script,
)
from src.scheduler.cron import CronBackend
from src.scheduler.detect import (
    BACKEND_CRON,
    BACKEND_LAUNCHD,
    BACKEND_SYSTEMD,
    BACKEND_WINDOWS,
    SUPPORTED_BACKENDS,
    detect_backend,
)
from src.scheduler.launchd import LaunchdBackend
from src.scheduler.manual import render_manual_instructions
from src.scheduler.systemd import SystemdBackend
from src.scheduler.windows import WindowsBackend

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


def _repo_root() -> Path:
    """リポジトリルートのパスを返す（src/cli.py の2階層上）。"""
    return Path(__file__).resolve().parent.parent


def _build_backend(
    backend_name: str,
    config: AppConfig,
    wrapper_script_path: Path,
    *,
    repo_root: Path | None = None,
    config_path: str | None = None,
    db_path: str | None = None,
) -> SchedulerBackend:
    timezone = config.schedule.timezone
    times = config.schedule.times
    if backend_name == BACKEND_CRON:
        return CronBackend(timezone, times, wrapper_script_path)
    if backend_name == BACKEND_SYSTEMD:
        return SystemdBackend(timezone, times, wrapper_script_path)
    if backend_name == BACKEND_LAUNCHD:
        return LaunchdBackend(timezone, times, wrapper_script_path)
    if backend_name == BACKEND_WINDOWS:
        # Windowsはbashラッパースクリプトに依存せず、uv runを直接呼び出すため
        # repo_root/config_path/db_pathが必要になる。
        return WindowsBackend(
            timezone, times, config.llm.provider, repo_root, config_path, db_path
        )
    raise ValueError(f"未対応のスケジューラです: {backend_name}")


def cmd_schedule_install(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    repo_root = _repo_root()

    mismatch_msg = warn_if_timezone_mismatch(config.schedule.timezone)
    if mismatch_msg:
        logger.warning(mismatch_msg)

    try:
        backend_name = detect_backend(args.scheduler)
        wrapper_script_path = write_wrapper_script(repo_root, args.config, args.db)
        backend = _build_backend(
            backend_name,
            config,
            wrapper_script_path,
            repo_root=repo_root,
            config_path=args.config,
            db_path=args.db,
        )
        backend.install()
    except Exception as exc:
        logger.error("スケジューラへの自動登録に失敗しました: %s", exc)
        print(render_manual_instructions(config, repo_root, args.config, args.db))
        return 1

    logger.info("スケジューラ(%s)への登録が完了しました。", backend_name)
    return 0


def cmd_schedule_uninstall(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    repo_root = _repo_root()
    try:
        backend_name = detect_backend(args.scheduler)
        wrapper_script_path = repo_root / WRAPPER_SCRIPT_RELATIVE_PATH
        backend = _build_backend(
            backend_name,
            config,
            wrapper_script_path,
            repo_root=repo_root,
            config_path=args.config,
            db_path=args.db,
        )
        backend.uninstall()
    except Exception as exc:
        logger.error("スケジューラ登録の削除に失敗しました: %s", exc)
        return 1
    return 0


def cmd_schedule_status(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    repo_root = _repo_root()
    try:
        backend_name = detect_backend(args.scheduler)
        wrapper_script_path = repo_root / WRAPPER_SCRIPT_RELATIVE_PATH
        backend = _build_backend(
            backend_name,
            config,
            wrapper_script_path,
            repo_root=repo_root,
            config_path=args.config,
            db_path=args.db,
        )
        installed = backend.status()
    except Exception as exc:
        logger.error("スケジューラ登録状況の確認に失敗しました: %s", exc)
        return 1

    print(f"scheduler={backend_name} installed={installed}")
    return 0


def cmd_schedule_preview(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    repo_root = _repo_root()
    try:
        backend_name = detect_backend(args.scheduler)
        wrapper_script_path = repo_root / WRAPPER_SCRIPT_RELATIVE_PATH
        backend = _build_backend(
            backend_name,
            config,
            wrapper_script_path,
            repo_root=repo_root,
            config_path=args.config,
            db_path=args.db,
        )
    except Exception as exc:
        logger.error("プレビューの生成に失敗しました: %s", exc)
        return 1

    print(f"# scheduler={backend_name}")
    print(backend.render())
    return 0


def _add_scheduler_option(subparser: argparse.ArgumentParser) -> None:
    subparser.add_argument(
        "--scheduler",
        choices=SUPPORTED_BACKENDS,
        default=None,
        help="使用するスケジューラを明示的に指定する（未指定時はOS判定に基づき自動選択）",
    )


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

    schedule_parser = subparsers.add_parser(
        "schedule", help="OSスケジューラ(cron/systemd/launchd)への登録を管理する"
    )
    schedule_subparsers = schedule_parser.add_subparsers(
        dest="schedule_command", required=True
    )

    install_parser = schedule_subparsers.add_parser(
        "install", help="OSスケジューラへ冪等に登録する"
    )
    _add_scheduler_option(install_parser)
    install_parser.set_defaults(func=cmd_schedule_install)

    uninstall_parser = schedule_subparsers.add_parser(
        "uninstall", help="OSスケジューラから自社エントリのみを削除する"
    )
    _add_scheduler_option(uninstall_parser)
    uninstall_parser.set_defaults(func=cmd_schedule_uninstall)

    status_parser = schedule_subparsers.add_parser(
        "status", help="OSスケジューラへの登録状況を表示する"
    )
    _add_scheduler_option(status_parser)
    status_parser.set_defaults(func=cmd_schedule_status)

    preview_parser = schedule_subparsers.add_parser(
        "preview", help="実際には登録せず、登録内容のプレビューのみを表示する"
    )
    _add_scheduler_option(preview_parser)
    preview_parser.set_defaults(func=cmd_schedule_preview)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    exit_code = args.func(args)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
