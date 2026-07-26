"""launchd user agent への登録バックエンド（macOS）。

固定ラベル名（`src/scheduler/base.py` の LAUNCHD_LABEL）でplistファイルを
丸ごと生成・上書きすることで冪等に更新する。
"""

from __future__ import annotations

import logging
import plistlib
import subprocess
from pathlib import Path

from src.scheduler.base import LAUNCHD_LABEL, MARKER_ID, SchedulerBackend

logger = logging.getLogger(__name__)

LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"


def launchd_plist_path() -> Path:
    return LAUNCH_AGENTS_DIR / f"{LAUNCHD_LABEL}.plist"


def parse_time_to_calendar_interval(time_str: str) -> dict:
    """"HH:MM" 形式の文字列を launchd StartCalendarInterval の1エントリに変換する。"""
    try:
        hour_str, minute_str = time_str.split(":")
        hour, minute = int(hour_str), int(minute_str)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"不正な時刻形式です（HH:MM形式で指定してください）: {time_str}") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"時刻の範囲が不正です: {time_str}")
    return {"Hour": hour, "Minute": minute}


def build_plist_dict(wrapper_script_path: Path, times: list[str]) -> dict:
    """news-digest用のplist内容を辞書として組み立てる。

    タイムゾーンはlaunchd自体には設定項目がなく、OSのシステムタイムゾーンに
    従って実行されるため、呼び出し元（cli.py）でタイムゾーン差異の警告を出す。
    """
    log_dir = wrapper_script_path.parent
    return {
        "Label": LAUNCHD_LABEL,
        "Comment": f"{MARKER_ID} が生成、手動編集しないでください",
        "ProgramArguments": ["/bin/bash", str(wrapper_script_path)],
        "StartCalendarInterval": [parse_time_to_calendar_interval(t) for t in times],
        "StandardOutPath": str(log_dir / "launchd.log"),
        "StandardErrorPath": str(log_dir / "launchd.err.log"),
    }


def render_plist_text(wrapper_script_path: Path, times: list[str]) -> str:
    """plistの内容をプレビュー用テキスト（XML）として返す。"""
    data = build_plist_dict(wrapper_script_path, times)
    return plistlib.dumps(data, sort_keys=False).decode("utf-8")


def run_launchctl_bootout() -> None:
    """`launchctl bootout gui/<uid>/<label>` 相当の処理を実行する（存在しない場合は無視）。"""
    _run_launchctl(["bootout", f"gui/{_uid()}/{LAUNCHD_LABEL}"], check=False)


def run_launchctl_bootstrap(plist_path: Path) -> None:
    """`launchctl bootstrap gui/<uid> <plist>` 相当の処理を実行する。"""
    _run_launchctl(["bootstrap", f"gui/{_uid()}", str(plist_path)])


def run_launchctl_print() -> bool:
    """`launchctl print gui/<uid>/<label>` の結果からロード済みかどうかを返す。"""
    try:
        result = subprocess.run(
            ["launchctl", "print", f"gui/{_uid()}/{LAUNCHD_LABEL}"],
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _uid() -> int:
    import os

    return os.getuid()


def _run_launchctl(args: list[str], check: bool = True) -> None:
    try:
        result = subprocess.run(
            ["launchctl", *args], capture_output=True, text=True, timeout=15, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"launchctl {' '.join(args)} の実行に失敗しました: {exc}") from exc

    if check and result.returncode != 0:
        raise RuntimeError(f"launchctl {' '.join(args)} が失敗しました: {result.stderr.strip()}")


class LaunchdBackend(SchedulerBackend):
    """launchd user agent バックエンド。"""

    def __init__(self, timezone: str, times: list[str], wrapper_script_path: Path):
        self.timezone = timezone
        self.times = times
        self.wrapper_script_path = wrapper_script_path

    def render(self) -> str:
        return f"# {launchd_plist_path()}\n{render_plist_text(self.wrapper_script_path, self.times)}"

    def install(self) -> None:
        LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
        plist_path = launchd_plist_path()
        data = build_plist_dict(self.wrapper_script_path, self.times)
        with plist_path.open("wb") as f:
            plistlib.dump(data, f)

        # 冪等な再読み込み: 既にロード済みならbootoutしてからbootstrapする。
        run_launchctl_bootout()
        run_launchctl_bootstrap(plist_path)
        logger.info("launchd user agentへの登録が完了しました（%d件のエントリ）。", len(self.times))

    def uninstall(self) -> None:
        plist_path = launchd_plist_path()
        if not plist_path.exists():
            logger.info("launchd user agentにnews-digestは登録されていません。")
            return
        run_launchctl_bootout()
        plist_path.unlink(missing_ok=True)
        logger.info("launchd user agentからの削除が完了しました。")

    def status(self) -> bool:
        return launchd_plist_path().exists()
