"""Windowsタスクスケジューラへの登録バックエンド。

固定タスク名（`src/scheduler/base.py` の WINDOWS_TASK_NAME）で
`Register-ScheduledTask -Force` を実行することで冪等に登録・更新する。

他バックエンド（cron/systemd/launchd）と異なり、`#!/bin/bash` 前提の
ラッパースクリプト（`write_wrapper_script()`）はWindows上でそのまま
実行できないため、Windowsバックエンドはラッパースクリプトに依存せず、
タスクのアクションとして `uv run news-digest --config ... --db ... run`
を直接呼び出す構成にしている。

本バックエンドは実験的（best-effort）機能であり、実際のWindows環境での
動作検証はスコープ外。コマンド構築レベルでのテストに留める。
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from src.scheduler.base import WINDOWS_TASK_NAME, SchedulerBackend, resolve_uv_path

logger = logging.getLogger(__name__)


def parse_time_to_at_string(time_str: str) -> str:
    """"HH:MM" 形式の文字列を検証し、`-At` オプションにそのまま使える文字列を返す。"""
    try:
        hour_str, minute_str = time_str.split(":")
        hour, minute = int(hour_str), int(minute_str)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"不正な時刻形式です（HH:MM形式で指定してください）: {time_str}") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"時刻の範囲が不正です: {time_str}")
    return f"{hour:02d}:{minute:02d}"


def build_register_task_script(
    times: list[str],
    provider: str,
    repo_root: Path,
    config_path: str,
    db_path: str,
    uv_path: str | None = None,
) -> str:
    """`Register-ScheduledTask` を冪等に実行するPowerShellスクリプトを組み立てる。

    provider が "claude-code-cli" の場合、対話ログオンセッション内で実行する
    必要があるため `-LogonType Interactive` を付与する（cron/systemdでの
    claude-code-cliプロバイダー注意事項と同様の事情）。API系プロバイダー
    （claude / local-ai）はAPIキー等の環境変数のみで完結するためこの制約は
    緩く、非対話（バッチ/サービス）ログオンでも動作しやすい。
    """
    if not times:
        raise ValueError("times が空です。少なくとも1つの時刻を指定してください。")

    at_strings = [parse_time_to_at_string(t) for t in times]
    resolved_uv_path = uv_path if uv_path is not None else resolve_uv_path()

    arguments = f'run news-digest --config "{config_path}" --db "{db_path}" run'

    trigger_lines = "\n".join(
        f'$triggers += New-ScheduledTaskTrigger -Daily -At "{at}"' for at in at_strings
    )

    lines = [
        "$ErrorActionPreference = 'Stop'",
        f'$action = New-ScheduledTaskAction -Execute "{resolved_uv_path}" '
        f'-Argument \'{arguments}\' -WorkingDirectory "{repo_root}"',
        "$triggers = @()",
        trigger_lines,
        "$settings = New-ScheduledTaskSettingsSet "
        "-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries",
    ]

    register_command = (
        f'Register-ScheduledTask -TaskName "{WINDOWS_TASK_NAME}" '
        "-Action $action -Trigger $triggers -Settings $settings -Force"
    )
    if provider == "claude-code-cli":
        # 対話ログオンセッションの文脈で実行させる必要があるため付与する。
        register_command += " -LogonType Interactive"

    lines.append(register_command)
    return "\n".join(lines) + "\n"


def run_powershell(script: str) -> subprocess.CompletedProcess:
    """`powershell.exe -NoProfile -Command <script>` を実行する（実行部分の分離）。"""
    try:
        return subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"powershell.exe の実行に失敗しました: {exc}") from exc


def run_register_scheduled_task(script: str) -> None:
    """タスク登録スクリプトを実行する。失敗時は例外を送出する。"""
    result = run_powershell(script)
    if result.returncode != 0:
        raise RuntimeError(
            f"Register-ScheduledTask が失敗しました: {result.stderr.strip()}"
        )


def run_unregister_scheduled_task() -> None:
    """`Unregister-ScheduledTask` 相当の処理を実行する（存在しない場合は無視）。"""
    script = (
        f'if (Get-ScheduledTask -TaskName "{WINDOWS_TASK_NAME}" '
        "-ErrorAction SilentlyContinue) {\n"
        f'  Unregister-ScheduledTask -TaskName "{WINDOWS_TASK_NAME}" -Confirm:$false\n'
        "}\n"
    )
    result = run_powershell(script)
    if result.returncode != 0:
        raise RuntimeError(
            f"Unregister-ScheduledTask が失敗しました: {result.stderr.strip()}"
        )


def run_get_scheduled_task_exists() -> bool:
    """`Get-ScheduledTask -TaskName <name>` でタスクが存在するかどうかを返す。"""
    script = (
        f'if (Get-ScheduledTask -TaskName "{WINDOWS_TASK_NAME}" '
        "-ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
    )
    result = run_powershell(script)
    return result.returncode == 0


class WindowsBackend(SchedulerBackend):
    """Windowsタスクスケジューラ バックエンド（実験的機能）。"""

    def __init__(
        self,
        timezone: str,
        times: list[str],
        provider: str,
        repo_root: Path,
        config_path: str,
        db_path: str,
    ):
        self.timezone = timezone
        self.times = times
        self.provider = provider
        self.repo_root = repo_root
        self.config_path = config_path
        self.db_path = db_path

    def render(self) -> str:
        script = build_register_task_script(
            self.times, self.provider, self.repo_root, self.config_path, self.db_path
        )
        return f"# タスクスケジューラ タスク名: {WINDOWS_TASK_NAME}\n{script}"

    def install(self) -> None:
        script = build_register_task_script(
            self.times, self.provider, self.repo_root, self.config_path, self.db_path
        )
        run_register_scheduled_task(script)
        logger.info(
            "Windowsタスクスケジューラへの登録が完了しました（%d件のエントリ）。",
            len(self.times),
        )

    def uninstall(self) -> None:
        run_unregister_scheduled_task()
        logger.info("Windowsタスクスケジューラからの削除が完了しました。")

    def status(self) -> bool:
        return run_get_scheduled_task_exists()
