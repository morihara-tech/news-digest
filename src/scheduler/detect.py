"""実行環境（OS/利用可能なスケジューラ）を判定するモジュール。

推奨順位: Linux -> systemd(user instance)優先、利用不可ならcronにフォールバック。
macOS -> launchd。
将来Windows等を追加しやすいよう、判定結果は文字列（Literal）で返す。
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess

# 対応済みバックエンド名。Enum化するほどの複雑さはないため文字列で統一する。
BACKEND_CRON = "cron"
BACKEND_SYSTEMD = "systemd"
BACKEND_LAUNCHD = "launchd"
BACKEND_WINDOWS = "windows"

SUPPORTED_BACKENDS = (BACKEND_CRON, BACKEND_SYSTEMD, BACKEND_LAUNCHD, BACKEND_WINDOWS)


def get_platform_system() -> str:
    """`platform.system()` の薄いラッパー（テストでmonkeypatchしやすくするため）。"""
    return platform.system()


def is_systemctl_available() -> bool:
    """`systemctl` コマンドが存在するかどうかを判定する。"""
    return shutil.which("systemctl") is not None


def is_systemd_user_instance_available() -> bool:
    """systemd の user instance が利用可能かどうかをベストエフォートで判定する。

    `systemctl --user status` 相当のコマンドが正常応答するかで判定する。
    XDG_RUNTIME_DIR が未設定の環境（sshログイン時にlingerが無効等）では
    user instanceに接続できないことが多いため、その簡易チェックも行う。
    """
    if not is_systemctl_available():
        return False
    if not os.environ.get("XDG_RUNTIME_DIR"):
        return False
    return run_systemctl_user_status() == 0


def run_systemctl_user_status() -> int:
    """`systemctl --user status` を実行し終了コードを返す（実コマンド実行部分を分離）。

    コマンド実行自体に失敗した場合（コマンド不在等）は 1 を返す。
    """
    try:
        result = subprocess.run(
            ["systemctl", "--user", "status"],
            capture_output=True,
            timeout=5,
            check=False,
        )
        return result.returncode
    except (OSError, subprocess.SubprocessError):
        return 1


def detect_backend(override: str | None = None) -> str:
    """利用するスケジューラバックエンドを判定する。

    override が指定されていればそれを検証のうえそのまま返す。
    未指定の場合はOS判定に基づき推奨バックエンドを返す。
    """
    if override is not None:
        if override not in SUPPORTED_BACKENDS:
            raise ValueError(
                f"未対応のスケジューラです: {override}. "
                f"対応済み: {', '.join(SUPPORTED_BACKENDS)}"
            )
        return override

    system = get_platform_system()
    if system == "Darwin":
        return BACKEND_LAUNCHD
    if system == "Linux":
        if is_systemd_user_instance_available():
            return BACKEND_SYSTEMD
        return BACKEND_CRON
    if system == "Windows":
        return BACKEND_WINDOWS

    raise ValueError(
        f"未対応のOSです: {system}. --scheduler オプションで明示的に指定してください。"
    )
