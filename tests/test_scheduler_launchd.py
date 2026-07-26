from __future__ import annotations

from pathlib import Path

import pytest

from src.scheduler.launchd import (
    LaunchdBackend,
    build_plist_dict,
    parse_time_to_calendar_interval,
    render_plist_text,
)


def test_parse_time_to_calendar_interval():
    assert parse_time_to_calendar_interval("08:00") == {"Hour": 8, "Minute": 0}
    assert parse_time_to_calendar_interval("23:59") == {"Hour": 23, "Minute": 59}


@pytest.mark.parametrize("invalid", ["25:00", "08:60", "invalid"])
def test_parse_time_to_calendar_interval_invalid_raises(invalid: str):
    with pytest.raises(ValueError):
        parse_time_to_calendar_interval(invalid)


def test_build_plist_dict_multiple_times(tmp_path: Path):
    script = tmp_path / "run-news-digest.sh"
    data = build_plist_dict(script, ["08:00", "20:30"])
    assert data["Label"] == "tech.morihara.news-digest"
    assert data["ProgramArguments"] == ["/bin/bash", str(script)]
    assert data["StartCalendarInterval"] == [
        {"Hour": 8, "Minute": 0},
        {"Hour": 20, "Minute": 30},
    ]


def test_render_plist_text_is_valid_xml(tmp_path: Path):
    script = tmp_path / "run-news-digest.sh"
    text = render_plist_text(script, ["08:00"])
    assert text.startswith("<?xml")
    assert "tech.morihara.news-digest" in text


def test_launchd_backend_install_writes_plist_and_reloads(tmp_path: Path, monkeypatch):
    plist_path = tmp_path / "LaunchAgents" / "tech.morihara.news-digest.plist"
    monkeypatch.setattr("src.scheduler.launchd.LAUNCH_AGENTS_DIR", plist_path.parent)
    monkeypatch.setattr("src.scheduler.launchd.launchd_plist_path", lambda: plist_path)

    calls = []
    monkeypatch.setattr(
        "src.scheduler.launchd.run_launchctl_bootout", lambda: calls.append("bootout")
    )
    monkeypatch.setattr(
        "src.scheduler.launchd.run_launchctl_bootstrap",
        lambda path: calls.append(("bootstrap", path)),
    )

    script = tmp_path / "run-news-digest.sh"
    backend = LaunchdBackend("Asia/Tokyo", ["08:00"], script)
    backend.install()

    assert plist_path.exists()
    assert calls[0] == "bootout"
    assert calls[1] == ("bootstrap", plist_path)


def test_launchd_backend_uninstall_removes_plist(tmp_path: Path, monkeypatch):
    plist_path = tmp_path / "LaunchAgents" / "tech.morihara.news-digest.plist"
    plist_path.parent.mkdir(parents=True)
    plist_path.write_text("dummy", encoding="utf-8")

    monkeypatch.setattr("src.scheduler.launchd.launchd_plist_path", lambda: plist_path)
    monkeypatch.setattr("src.scheduler.launchd.run_launchctl_bootout", lambda: None)

    script = tmp_path / "run-news-digest.sh"
    backend = LaunchdBackend("Asia/Tokyo", ["08:00"], script)
    backend.uninstall()

    assert not plist_path.exists()


def test_launchd_backend_status_reflects_file_presence(tmp_path: Path, monkeypatch):
    plist_path = tmp_path / "LaunchAgents" / "tech.morihara.news-digest.plist"
    monkeypatch.setattr("src.scheduler.launchd.launchd_plist_path", lambda: plist_path)

    script = tmp_path / "run-news-digest.sh"
    backend = LaunchdBackend("Asia/Tokyo", ["08:00"], script)
    assert backend.status() is False

    plist_path.parent.mkdir(parents=True)
    plist_path.write_text("dummy", encoding="utf-8")
    assert backend.status() is True
