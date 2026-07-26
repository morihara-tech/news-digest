"""スケジューラバックエンド共通のインターフェースとヘルパー。

cron/systemd/launchd の各バックエンド（`src/scheduler/cron.py` 等）が
共通で使う定数・インターフェース・ラッパースクリプト生成処理・
タイムゾーン検出処理をここにまとめる。
"""

from __future__ import annotations

import logging
import os
import shutil
import stat
from abc import ABC, abstractmethod
from pathlib import Path

logger = logging.getLogger(__name__)

# 自社エントリを識別するための固定マーカー。
# cron.py はコメント行として、systemd.py/launchd.py は
# ユニット名/ラベル名として、この識別子を使って冪等に登録・削除する。
MARKER_ID = "news-digest-scheduler"
MARKER_COMMENT_BEGIN = f"# BEGIN {MARKER_ID} (auto-generated, do not edit)"
MARKER_COMMENT_END = f"# END {MARKER_ID}"

# systemd user unit名 / launchd label名（固定・冪等更新の対象）。
SYSTEMD_UNIT_NAME = "news-digest"
LAUNCHD_LABEL = "tech.morihara.news-digest"

# ラッパースクリプトの既定パス（リポジトリルートからの相対パス）。
# state/ は .gitignore 対象であり、install時にランタイム生成する。
WRAPPER_SCRIPT_RELATIVE_PATH = "state/run-news-digest.sh"


class SchedulerBackend(ABC):
    """OSスケジューラバックエンドの共通インターフェース。"""

    @abstractmethod
    def render(self) -> str:
        """登録される内容のプレビュー文字列を返す（実際には登録しない）。"""

    @abstractmethod
    def install(self) -> None:
        """スケジューラへ冪等に登録する。失敗時は例外を送出する。"""

    @abstractmethod
    def uninstall(self) -> None:
        """自社マーカーのエントリのみを冪等に削除する。"""

    @abstractmethod
    def status(self) -> bool:
        """自社マーカーが登録済みかどうかを返す。"""


def resolve_uv_path() -> str:
    """`uv` コマンドの絶対パスを解決する。

    見つからない場合はコマンド名 "uv" のまま返し、警告ログを出す
    （PATHが通っている実行環境であれば動作する可能性があるため）。
    """
    uv_path = shutil.which("uv")
    if uv_path is None:
        logger.warning(
            "uv コマンドが見つかりませんでした。PATHが通っている前提で "
            "'uv' コマンド名のままラッパースクリプトを生成します。"
        )
        return "uv"
    return uv_path


def build_wrapper_script_content(
    repo_root: Path, config_path: str, db_path: str
) -> str:
    """ラッパースクリプト（state/run-news-digest.sh）の内容を組み立てる。"""
    uv_path = resolve_uv_path()
    return (
        "#!/bin/bash\n"
        f"# {MARKER_ID} が生成したラッパースクリプト。手動編集しないでください。\n"
        "set -euo pipefail\n"
        f'cd "{repo_root}"\n'
        f'exec "{uv_path}" run news-digest --config "{config_path}" --db "{db_path}" run\n'
    )


def write_wrapper_script(
    repo_root: Path, config_path: str, db_path: str
) -> Path:
    """ラッパースクリプトを生成し実行権限を付与して、そのパスを返す。"""
    script_path = repo_root / WRAPPER_SCRIPT_RELATIVE_PATH
    script_path.parent.mkdir(parents=True, exist_ok=True)
    content = build_wrapper_script_content(repo_root, config_path, db_path)
    script_path.write_text(content, encoding="utf-8")
    current_mode = script_path.stat().st_mode
    script_path.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return script_path


def detect_system_timezone() -> str | None:
    """OSのタイムゾーンをベストエフォートで検出する。

    /etc/localtime のシンボリックリンク解決を優先し、
    失敗した場合は time.tzname へフォールバックする。
    検出できなければ None を返す。
    """
    localtime_path = Path("/etc/localtime")
    try:
        if localtime_path.is_symlink():
            resolved = os.readlink(localtime_path)
            # 例: /usr/share/zoneinfo/Asia/Tokyo -> Asia/Tokyo
            marker = "zoneinfo/"
            if marker in resolved:
                return resolved.split(marker, 1)[1]
    except OSError:
        pass

    try:
        import time

        tzname = time.tzname[0]
        if tzname:
            return tzname
    except Exception:
        pass

    return None


def warn_if_timezone_mismatch(config_timezone: str) -> str | None:
    """configのタイムゾーンとシステムのタイムゾーンが異なる場合、警告メッセージを返す。

    一致する場合や検出できない場合は None を返す（呼び出し元は
    Noneでなければログ等で警告を表示する）。
    """
    system_tz = detect_system_timezone()
    if system_tz is None:
        return None
    if system_tz == config_timezone:
        return None
    return (
        f"config.yaml の schedule.timezone ({config_timezone}) と "
        f"システムのタイムゾーン ({system_tz}) が異なります。"
        "意図した時刻に実行されない可能性があるためご確認ください。"
    )
