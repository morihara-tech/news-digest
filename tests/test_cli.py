from __future__ import annotations

from src.cli import build_parser, cmd_scrapers_check
from src.core.state import StateStore


def _run_scrapers_check(db_path) -> int:
    parser = build_parser()
    args = parser.parse_args(["--db", str(db_path), "scrapers", "check"])
    return cmd_scrapers_check(args)


def test_scrapers_check_no_records_returns_zero(tmp_path, capsys):
    db_path = tmp_path / "digest.db"
    with StateStore(db_path):
        pass  # DBファイルのみ作成し、source_healthは空のまま

    exit_code = _run_scrapers_check(db_path)
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "source_health レコードがありません" in out


def test_scrapers_check_all_ok_returns_zero(tmp_path, capsys):
    db_path = tmp_path / "digest.db"
    with StateStore(db_path) as store:
        store.record_source_health("example-blog", status="ok", article_count=2)

    exit_code = _run_scrapers_check(db_path)
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "example-blog" in out
    assert "ok" in out


def test_scrapers_check_error_status_returns_one(tmp_path, capsys):
    db_path = tmp_path / "digest.db"
    with StateStore(db_path) as store:
        store.record_source_health("example-blog", status="ok", article_count=2)
        store.record_source_health("broken-blog", status="error", article_count=0, error="boom")

    exit_code = _run_scrapers_check(db_path)
    assert exit_code == 1
    out = capsys.readouterr().out
    assert "broken-blog" in out
    assert "boom" in out
