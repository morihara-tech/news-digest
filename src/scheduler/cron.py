"""ユーザーcrontabへの登録バックエンド。

`crontab -l` で既存の内容を読み取り、固定マーカーブロック
（`src/scheduler/base.py` の MARKER_COMMENT_BEGIN/END）で自社エントリを
特定して全置換したうえで `crontab -` で書き戻す。
他のcrontabエントリ（マーカーブロック外の行）には影響しない。
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

from src.scheduler.base import (
    MARKER_COMMENT_BEGIN,
    MARKER_COMMENT_END,
    SchedulerBackend,
)

logger = logging.getLogger(__name__)

# マーカーブロック全体（BEGIN行〜END行、両端含む）にマッチする正規表現。
_MARKER_BLOCK_RE = re.compile(
    re.escape(MARKER_COMMENT_BEGIN) + r".*?" + re.escape(MARKER_COMMENT_END) + r"\n?",
    re.DOTALL,
)


def parse_time_to_cron_fields(time_str: str) -> tuple[str, str]:
    """"HH:MM" 形式の文字列を cron の (分, 時) フィールドに変換する。"""
    try:
        hour_str, minute_str = time_str.split(":")
        hour, minute = int(hour_str), int(minute_str)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"不正な時刻形式です（HH:MM形式で指定してください）: {time_str}") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"時刻の範囲が不正です: {time_str}")
    return str(minute), str(hour)


def run_crontab_list() -> str:
    """`crontab -l` を実行し現在のcrontab内容を返す（実コマンド実行部分を分離）。

    crontabが未設定の場合、`crontab -l` は非ゼロ終了することがあるが、
    その場合は空文字列を返す（エラーとして扱わない）。
    """
    try:
        result = subprocess.run(
            ["crontab", "-l"], capture_output=True, text=True, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"crontab -l の実行に失敗しました: {exc}") from exc

    if result.returncode != 0:
        # crontab未設定時のエラーメッセージ（"no crontab for <user>" 等）は正常系として扱う。
        return ""
    return result.stdout


def run_crontab_write(content: str) -> None:
    """`crontab -` を実行しcrontabの内容を書き換える（実コマンド実行部分を分離）。"""
    try:
        result = subprocess.run(
            ["crontab", "-"], input=content, text=True, capture_output=True, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"crontab の書き込みに失敗しました: {exc}") from exc

    if result.returncode != 0:
        raise RuntimeError(f"crontab の書き込みに失敗しました: {result.stderr.strip()}")


def build_marker_block(timezone: str, times: list[str], wrapper_script_path: Path) -> str:
    """自社管理のマーカーブロック（コメント+cronエントリ）を組み立てる。"""
    lines = [MARKER_COMMENT_BEGIN]
    lines.append(f"CRON_TZ={timezone}")
    for time_str in times:
        minute, hour = parse_time_to_cron_fields(time_str)
        lines.append(f'{minute} {hour} * * * "{wrapper_script_path}"')
    lines.append(MARKER_COMMENT_END)
    return "\n".join(lines) + "\n"


def _strip_marker_block(existing: str) -> str:
    """既存crontab内容から自社マーカーブロックを取り除いた文字列を返す。"""
    return _MARKER_BLOCK_RE.sub("", existing)


def replace_marker_block(existing: str, new_block: str) -> str:
    """既存crontab内容の自社マーカーブロックを新しい内容で全置換する（冪等）。

    既存に自社ブロックがなければ末尾に追加する。他のエントリは保持する。
    """
    stripped = _strip_marker_block(existing)
    stripped = stripped.rstrip("\n")
    if stripped:
        return stripped + "\n\n" + new_block
    return new_block


def remove_marker_block(existing: str) -> str:
    """既存crontab内容から自社マーカーブロックのみを取り除く。"""
    return _strip_marker_block(existing)


def has_marker_block(existing: str) -> bool:
    return MARKER_COMMENT_BEGIN in existing


class CronBackend(SchedulerBackend):
    """cronバックエンド。"""

    def __init__(self, timezone: str, times: list[str], wrapper_script_path: Path):
        self.timezone = timezone
        self.times = times
        self.wrapper_script_path = wrapper_script_path

    def render(self) -> str:
        return build_marker_block(self.timezone, self.times, self.wrapper_script_path)

    def install(self) -> None:
        existing = run_crontab_list()
        new_block = self.render()
        updated = replace_marker_block(existing, new_block)
        run_crontab_write(updated)
        logger.info("crontabへの登録が完了しました（%d件のエントリ）。", len(self.times))

    def uninstall(self) -> None:
        existing = run_crontab_list()
        if not has_marker_block(existing):
            logger.info("crontabに%sのエントリは登録されていません。", "news-digest")
            return
        updated = remove_marker_block(existing)
        run_crontab_write(updated)
        logger.info("crontabからの削除が完了しました。")

    def status(self) -> bool:
        existing = run_crontab_list()
        return has_marker_block(existing)
