from __future__ import annotations

from pathlib import Path

import pytest

from src import cli


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(
        """
        schedule:
          timezone: Asia/Tokyo
          times: ["08:00"]
        """,
        encoding="utf-8",
    )
    return path


def test_build_parser_schedule_subcommands_parse():
    parser = cli.build_parser()
    for sub in ["install", "uninstall", "status", "preview"]:
        args = parser.parse_args(["schedule", sub, "--scheduler", "cron"])
        assert args.command == "schedule"
        assert args.schedule_command == sub
        assert args.scheduler == "cron"


def test_build_parser_schedule_without_subcommand_requires_one():
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["schedule"])


class _FakeBackend:
    def __init__(self, *args, **kwargs):
        self.installed = False
        self.rendered = "rendered-content"

    def render(self) -> str:
        return self.rendered

    def install(self) -> None:
        self.installed = True

    def uninstall(self) -> None:
        self.installed = False

    def status(self) -> bool:
        return self.installed


class _FailingBackend(_FakeBackend):
    def install(self) -> None:
        raise RuntimeError("boom")


def test_cmd_schedule_preview_prints_render(config_path: Path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "detect_backend", lambda override: "cron")
    monkeypatch.setattr(cli, "_build_backend", lambda name, config, path: _FakeBackend())

    parser = cli.build_parser()
    args = parser.parse_args(["--config", str(config_path), "schedule", "preview"])
    exit_code = args.func(args)

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "rendered-content" in captured.out


def test_cmd_schedule_install_success(config_path: Path, monkeypatch, tmp_path: Path):
    monkeypatch.setattr(cli, "detect_backend", lambda override: "cron")
    monkeypatch.setattr(cli, "warn_if_timezone_mismatch", lambda tz: None)
    monkeypatch.setattr(
        cli, "write_wrapper_script", lambda repo_root, config, db: tmp_path / "wrapper.sh"
    )
    backend = _FakeBackend()
    monkeypatch.setattr(cli, "_build_backend", lambda name, config, path: backend)

    parser = cli.build_parser()
    args = parser.parse_args(["--config", str(config_path), "schedule", "install"])
    exit_code = args.func(args)

    assert exit_code == 0
    assert backend.installed is True


def test_cmd_schedule_install_failure_prints_manual_instructions(
    config_path: Path, monkeypatch, tmp_path: Path, capsys
):
    monkeypatch.setattr(cli, "detect_backend", lambda override: "cron")
    monkeypatch.setattr(cli, "warn_if_timezone_mismatch", lambda tz: None)
    monkeypatch.setattr(
        cli, "write_wrapper_script", lambda repo_root, config, db: tmp_path / "wrapper.sh"
    )
    monkeypatch.setattr(cli, "_build_backend", lambda name, config, path: _FailingBackend())

    parser = cli.build_parser()
    args = parser.parse_args(["--config", str(config_path), "schedule", "install"])
    exit_code = args.func(args)

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "自動登録に失敗したため" in captured.out


def test_cmd_schedule_uninstall_calls_backend(config_path: Path, monkeypatch):
    monkeypatch.setattr(cli, "detect_backend", lambda override: "cron")
    backend = _FakeBackend()
    backend.installed = True
    monkeypatch.setattr(cli, "_build_backend", lambda name, config, path: backend)

    parser = cli.build_parser()
    args = parser.parse_args(["--config", str(config_path), "schedule", "uninstall"])
    exit_code = args.func(args)

    assert exit_code == 0
    assert backend.installed is False


def test_cmd_schedule_status_prints_status(config_path: Path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "detect_backend", lambda override: "cron")
    backend = _FakeBackend()
    backend.installed = True
    monkeypatch.setattr(cli, "_build_backend", lambda name, config, path: backend)

    parser = cli.build_parser()
    args = parser.parse_args(["--config", str(config_path), "schedule", "status"])
    exit_code = args.func(args)

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "scheduler=cron" in captured.out
    assert "installed=True" in captured.out
