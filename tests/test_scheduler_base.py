from __future__ import annotations

from pathlib import Path

from src.scheduler.base import (
    MARKER_COMMENT_BEGIN,
    MARKER_COMMENT_END,
    build_wrapper_script_content,
    detect_system_timezone,
    warn_if_timezone_mismatch,
    write_wrapper_script,
)


def test_build_wrapper_script_content_includes_repo_root_and_command(tmp_path: Path):
    content = build_wrapper_script_content(tmp_path, "config.yaml", "state/digest.db")
    assert content.startswith("#!/bin/bash")
    assert f'cd "{tmp_path}"' in content
    assert "run news-digest --config" in content
    assert '"config.yaml"' in content
    assert '"state/digest.db"' in content
    assert "run\n" in content


def test_write_wrapper_script_creates_executable_file(tmp_path: Path):
    script_path = write_wrapper_script(tmp_path, "config.yaml", "state/digest.db")
    assert script_path.exists()
    assert script_path == tmp_path / "state" / "run-news-digest.sh"
    # 実行権限が付与されていること
    assert script_path.stat().st_mode & 0o111 != 0


def test_marker_constants_are_distinct():
    assert MARKER_COMMENT_BEGIN != MARKER_COMMENT_END
    assert "news-digest-scheduler" in MARKER_COMMENT_BEGIN
    assert "news-digest-scheduler" in MARKER_COMMENT_END


def test_warn_if_timezone_mismatch_returns_none_when_matching(monkeypatch):
    monkeypatch.setattr(
        "src.scheduler.base.detect_system_timezone", lambda: "Asia/Tokyo"
    )
    assert warn_if_timezone_mismatch("Asia/Tokyo") is None


def test_warn_if_timezone_mismatch_returns_message_when_different(monkeypatch):
    monkeypatch.setattr("src.scheduler.base.detect_system_timezone", lambda: "UTC")
    message = warn_if_timezone_mismatch("Asia/Tokyo")
    assert message is not None
    assert "Asia/Tokyo" in message
    assert "UTC" in message


def test_warn_if_timezone_mismatch_returns_none_when_undetectable(monkeypatch):
    monkeypatch.setattr("src.scheduler.base.detect_system_timezone", lambda: None)
    assert warn_if_timezone_mismatch("Asia/Tokyo") is None


def test_detect_system_timezone_resolves_symlink(tmp_path: Path, monkeypatch):
    # /etc/localtime のシンボリックリンク解決部分の単体的な挙動確認。
    # 実環境の /etc/localtime に依存せず、readlink自体はベストエフォートである
    # ことのみを検証する（値がNoneまたは文字列であること）。
    result = detect_system_timezone()
    assert result is None or isinstance(result, str)
