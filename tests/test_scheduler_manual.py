from __future__ import annotations

from pathlib import Path

from src.config import AppConfig, ScheduleConfig
from src.scheduler.manual import render_manual_instructions


def test_render_manual_instructions_includes_all_methods(tmp_path: Path):
    config = AppConfig(schedule=ScheduleConfig(timezone="Asia/Tokyo", times=["08:00", "20:30"]))
    text = render_manual_instructions(config, tmp_path, "config.yaml", "state/digest.db")

    assert "方法1: cron" in text
    assert "方法2: systemd" in text
    assert "方法3: launchd" in text
    assert "CRON_TZ=Asia/Tokyo" in text
    assert "0 8 * * *" in text
    assert "30 20 * * *" in text
    assert "OnCalendar=*-*-* 08:00:00 Asia/Tokyo" in text
    assert "OnCalendar=*-*-* 20:30:00 Asia/Tokyo" in text
    assert str(tmp_path / "state" / "run-news-digest.sh") in text


def test_render_manual_instructions_embeds_repo_root_in_wrapper_script(tmp_path: Path):
    config = AppConfig()
    text = render_manual_instructions(config, tmp_path)
    assert f'cd "{tmp_path}"' in text
