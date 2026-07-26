"""systemd user timer への登録バックエンド（Linux）。

固定ユニット名（`src/scheduler/base.py` の SYSTEMD_UNIT_NAME）で
service/timer ユニットファイルを丸ごと生成・上書きすることで冪等に更新する。
ファイル全体が自社管理のため、cron.py のようなマーカーブロック方式は不要だが、
ユニット名自体を固定マーカーとして扱う。
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from src.scheduler.base import MARKER_ID, SYSTEMD_UNIT_NAME, SchedulerBackend

logger = logging.getLogger(__name__)

SYSTEMD_USER_DIR = Path.home() / ".config" / "systemd" / "user"


def systemd_service_path() -> Path:
    return SYSTEMD_USER_DIR / f"{SYSTEMD_UNIT_NAME}.service"


def systemd_timer_path() -> Path:
    return SYSTEMD_USER_DIR / f"{SYSTEMD_UNIT_NAME}.timer"


def build_service_unit_content(wrapper_script_path: Path) -> str:
    """news-digest.service の内容を組み立てる。"""
    return (
        "[Unit]\n"
        f"Description=news-digest 配信バッチ ({MARKER_ID} が生成、手動編集しないでください)\n"
        "\n"
        "[Service]\n"
        "Type=oneshot\n"
        f'ExecStart=/bin/bash "{wrapper_script_path}"\n'
    )


def build_timer_unit_content(timezone: str, times: list[str]) -> str:
    """news-digest.timer の内容を組み立てる。

    systemd v240以降のOnCalendarのTZ suffix形式（例:
    "OnCalendar=*-*-* 08:00:00 Asia/Tokyo"）を使い、複数timesは複数
    OnCalendar行として登録する。
    """
    lines = [
        "[Unit]",
        f"Description=news-digest 配信バッチのスケジュール ({MARKER_ID} が生成、手動編集しないでください)",
        "",
        "[Timer]",
    ]
    for time_str in times:
        lines.append(f"OnCalendar=*-*-* {time_str}:00 {timezone}")
    lines.append("Persistent=true")
    lines.extend(["", "[Install]", "WantedBy=timers.target"])
    return "\n".join(lines) + "\n"


def run_systemctl_daemon_reload() -> None:
    """`systemctl --user daemon-reload` を実行する（実コマンド実行部分を分離）。"""
    _run_systemctl(["daemon-reload"])


def run_systemctl_enable_now() -> None:
    """`systemctl --user enable --now news-digest.timer` を実行する。"""
    _run_systemctl(["enable", "--now", f"{SYSTEMD_UNIT_NAME}.timer"])


def run_systemctl_disable_now() -> None:
    """`systemctl --user disable --now news-digest.timer` を実行する。"""
    _run_systemctl(["disable", "--now", f"{SYSTEMD_UNIT_NAME}.timer"], check=False)


def run_systemctl_is_enabled() -> bool:
    """`systemctl --user is-enabled news-digest.timer` の結果からenabledかどうかを返す。"""
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-enabled", f"{SYSTEMD_UNIT_NAME}.timer"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and result.stdout.strip() == "enabled"


def _run_systemctl(args: list[str], check: bool = True) -> None:
    try:
        result = subprocess.run(
            ["systemctl", "--user", *args],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"systemctl --user {' '.join(args)} の実行に失敗しました: {exc}") from exc

    if check and result.returncode != 0:
        raise RuntimeError(
            f"systemctl --user {' '.join(args)} が失敗しました: {result.stderr.strip()}"
        )


class SystemdBackend(SchedulerBackend):
    """systemd user timer バックエンド。"""

    def __init__(self, timezone: str, times: list[str], wrapper_script_path: Path):
        self.timezone = timezone
        self.times = times
        self.wrapper_script_path = wrapper_script_path

    def render(self) -> str:
        service = build_service_unit_content(self.wrapper_script_path)
        timer = build_timer_unit_content(self.timezone, self.times)
        return (
            f"# {systemd_service_path()}\n{service}\n"
            f"# {systemd_timer_path()}\n{timer}"
        )

    def install(self) -> None:
        SYSTEMD_USER_DIR.mkdir(parents=True, exist_ok=True)
        systemd_service_path().write_text(
            build_service_unit_content(self.wrapper_script_path), encoding="utf-8"
        )
        systemd_timer_path().write_text(
            build_timer_unit_content(self.timezone, self.times), encoding="utf-8"
        )
        run_systemctl_daemon_reload()
        run_systemctl_enable_now()
        logger.info("systemd user timerへの登録が完了しました（%d件のエントリ）。", len(self.times))

    def uninstall(self) -> None:
        if not systemd_service_path().exists() and not systemd_timer_path().exists():
            logger.info("systemd user timerにnews-digestは登録されていません。")
            return
        run_systemctl_disable_now()
        systemd_service_path().unlink(missing_ok=True)
        systemd_timer_path().unlink(missing_ok=True)
        run_systemctl_daemon_reload()
        logger.info("systemd user timerからの削除が完了しました。")

    def status(self) -> bool:
        return systemd_service_path().exists() and systemd_timer_path().exists()
