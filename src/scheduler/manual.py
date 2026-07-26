"""自動登録できない/失敗した場合に表示する手動設定手順の生成モジュール。

README.md記載のcrontab/systemd/launchd手順と同等の内容を、
実際のリポジトリパス・config/dbパス・schedule設定を埋め込んで動的に構築する。
"""

from __future__ import annotations

from pathlib import Path

from src.config import AppConfig
from src.scheduler.base import (
    LAUNCHD_LABEL,
    SYSTEMD_UNIT_NAME,
    WRAPPER_SCRIPT_RELATIVE_PATH,
    build_wrapper_script_content,
)


def render_manual_instructions(
    config: AppConfig,
    repo_root: Path,
    config_path: str = "config.yaml",
    db_path: str = "state/digest.db",
) -> str:
    """自動登録に失敗した場合の手動設定手順テキストを生成する。"""
    times = config.schedule.times
    timezone = config.schedule.timezone
    wrapper_script_path = repo_root / WRAPPER_SCRIPT_RELATIVE_PATH

    sections = [
        "自動登録に失敗したため、以下の手順で手動設定してください。",
        "",
        "--- 共通: ラッパースクリプト ---",
        f"以下の内容で {wrapper_script_path} を作成し、実行権限を付与してください。",
        "```",
        build_wrapper_script_content(repo_root, config_path, db_path).rstrip("\n"),
        "```",
        f"chmod +x {wrapper_script_path}",
        "",
        "--- 方法1: cron ---",
        "`crontab -e` で以下の行を追加してください。",
        "```",
        f"CRON_TZ={timezone}",
    ]
    for time_str in times:
        hour, minute = time_str.split(":")
        sections.append(f'{int(minute)} {int(hour)} * * * "{wrapper_script_path}"')
    sections.append("```")

    sections.extend(
        [
            "",
            "--- 方法2: systemd (Linux, user timer) ---",
            f"~/.config/systemd/user/{SYSTEMD_UNIT_NAME}.service を作成:",
            "```",
            "[Unit]",
            "Description=news-digest 配信バッチ",
            "",
            "[Service]",
            "Type=oneshot",
            f'ExecStart=/bin/bash "{wrapper_script_path}"',
            "```",
            f"~/.config/systemd/user/{SYSTEMD_UNIT_NAME}.timer を作成:",
            "```",
            "[Unit]",
            "Description=news-digest 配信バッチのスケジュール",
            "",
            "[Timer]",
        ]
    )
    for time_str in times:
        sections.append(f"OnCalendar=*-*-* {time_str}:00 {timezone}")
    sections.extend(
        [
            "Persistent=true",
            "",
            "[Install]",
            "WantedBy=timers.target",
            "```",
            "登録:",
            "```",
            "systemctl --user daemon-reload",
            f"systemctl --user enable --now {SYSTEMD_UNIT_NAME}.timer",
            "```",
            "",
            "--- 方法3: launchd (macOS) ---",
            f"~/Library/LaunchAgents/{LAUNCHD_LABEL}.plist を作成し、"
            "ProgramArguments に "
            f'["/bin/bash", "{wrapper_script_path}"] 、'
            "StartCalendarInterval に "
            f"{[{'Hour': int(t.split(':')[0]), 'Minute': int(t.split(':')[1])} for t in times]} "
            "を設定してください。",
            "登録:",
            "```",
            f"launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/{LAUNCHD_LABEL}.plist",
            "```",
        ]
    )

    return "\n".join(sections) + "\n"
