from __future__ import annotations

from pathlib import Path

import pytest

from src.scheduler.cron import (
    CronBackend,
    build_marker_block,
    has_marker_block,
    parse_time_to_cron_fields,
    remove_marker_block,
    replace_marker_block,
    run_crontab_list,
)


def test_parse_time_to_cron_fields():
    assert parse_time_to_cron_fields("08:00") == ("0", "8")
    assert parse_time_to_cron_fields("23:59") == ("59", "23")


@pytest.mark.parametrize("invalid", ["25:00", "08:60", "not-a-time", "8"])
def test_parse_time_to_cron_fields_invalid_raises(invalid: str):
    with pytest.raises(ValueError):
        parse_time_to_cron_fields(invalid)


def test_build_marker_block_contains_tz_and_entries(tmp_path: Path):
    script = tmp_path / "run-news-digest.sh"
    block = build_marker_block("Asia/Tokyo", ["08:00", "20:30"], script)
    assert "CRON_TZ=Asia/Tokyo" in block
    assert "0 8 * * *" in block
    assert "30 20 * * *" in block
    assert str(script) in block
    assert block.startswith("# BEGIN")
    assert block.rstrip("\n").endswith("# END news-digest-scheduler")


def test_replace_marker_block_appends_when_no_existing_block(tmp_path: Path):
    script = tmp_path / "run-news-digest.sh"
    new_block = build_marker_block("Asia/Tokyo", ["08:00"], script)
    existing = "0 3 * * * /usr/bin/other-job\n"
    result = replace_marker_block(existing, new_block)
    assert "/usr/bin/other-job" in result
    assert new_block.strip() in result


def test_replace_marker_block_is_idempotent(tmp_path: Path):
    script = tmp_path / "run-news-digest.sh"
    new_block = build_marker_block("Asia/Tokyo", ["08:00"], script)
    existing = "0 3 * * * /usr/bin/other-job\n"

    once = replace_marker_block(existing, new_block)
    twice = replace_marker_block(once, new_block)

    assert once == twice
    assert twice.count("BEGIN news-digest-scheduler") == 1
    assert "/usr/bin/other-job" in twice


def test_replace_marker_block_updates_existing_content(tmp_path: Path):
    script = tmp_path / "run-news-digest.sh"
    old_block = build_marker_block("Asia/Tokyo", ["08:00"], script)
    new_block = build_marker_block("Asia/Tokyo", ["09:30"], script)

    existing = "0 3 * * * /usr/bin/other-job\n\n" + old_block
    result = replace_marker_block(existing, new_block)

    assert "0 8 * * *" not in result
    assert "30 9 * * *" in result
    assert "/usr/bin/other-job" in result


def test_remove_marker_block_removes_only_own_entries(tmp_path: Path):
    script = tmp_path / "run-news-digest.sh"
    block = build_marker_block("Asia/Tokyo", ["08:00"], script)
    existing = "0 3 * * * /usr/bin/other-job\n\n" + block

    result = remove_marker_block(existing)

    assert "/usr/bin/other-job" in result
    assert not has_marker_block(result)


def test_has_marker_block():
    assert has_marker_block("# BEGIN news-digest-scheduler (auto-generated, do not edit)\n")
    assert not has_marker_block("0 3 * * * /usr/bin/other-job\n")


def test_run_crontab_list_returns_empty_when_no_crontab(monkeypatch):
    class FakeResult:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(
        "src.scheduler.cron.subprocess.run", lambda *a, **k: FakeResult()
    )
    assert run_crontab_list() == ""


def test_cron_backend_install_replaces_marker_block(tmp_path: Path, monkeypatch):
    script = tmp_path / "run-news-digest.sh"
    backend = CronBackend("Asia/Tokyo", ["08:00"], script)

    monkeypatch.setattr(
        "src.scheduler.cron.run_crontab_list",
        lambda: "0 3 * * * /usr/bin/other-job\n",
    )
    written = {}

    def fake_write(content: str) -> None:
        written["content"] = content

    monkeypatch.setattr("src.scheduler.cron.run_crontab_write", fake_write)

    backend.install()

    assert "/usr/bin/other-job" in written["content"]
    assert "CRON_TZ=Asia/Tokyo" in written["content"]
    assert str(script) in written["content"]


def test_cron_backend_uninstall_removes_only_marker_block(tmp_path: Path, monkeypatch):
    script = tmp_path / "run-news-digest.sh"
    backend = CronBackend("Asia/Tokyo", ["08:00"], script)
    block = build_marker_block("Asia/Tokyo", ["08:00"], script)

    monkeypatch.setattr(
        "src.scheduler.cron.run_crontab_list",
        lambda: "0 3 * * * /usr/bin/other-job\n\n" + block,
    )
    written = {}
    monkeypatch.setattr(
        "src.scheduler.cron.run_crontab_write", lambda content: written.__setitem__("content", content)
    )

    backend.uninstall()

    assert "/usr/bin/other-job" in written["content"]
    assert not has_marker_block(written["content"])


def test_cron_backend_status_reflects_marker_presence(tmp_path: Path, monkeypatch):
    script = tmp_path / "run-news-digest.sh"
    backend = CronBackend("Asia/Tokyo", ["08:00"], script)

    monkeypatch.setattr("src.scheduler.cron.run_crontab_list", lambda: "")
    assert backend.status() is False

    block = build_marker_block("Asia/Tokyo", ["08:00"], script)
    monkeypatch.setattr("src.scheduler.cron.run_crontab_list", lambda: block)
    assert backend.status() is True
