from __future__ import annotations

from pathlib import Path

import pytest

from src.scheduler.base import WINDOWS_TASK_NAME
from src.scheduler.windows import (
    WindowsBackend,
    build_register_task_script,
    parse_time_to_at_string,
    run_get_scheduled_task_exists,
    run_powershell,
    run_register_scheduled_task,
    run_unregister_scheduled_task,
)


def test_parse_time_to_at_string():
    assert parse_time_to_at_string("08:00") == "08:00"
    assert parse_time_to_at_string("23:59") == "23:59"
    assert parse_time_to_at_string("8:5") == "08:05"


@pytest.mark.parametrize("invalid", ["25:00", "08:60", "invalid"])
def test_parse_time_to_at_string_invalid_raises(invalid: str):
    with pytest.raises(ValueError):
        parse_time_to_at_string(invalid)


def test_build_register_task_script_single_time(tmp_path: Path):
    script = build_register_task_script(
        ["08:00"],
        "claude",
        tmp_path,
        "config.yaml",
        "state/digest.db",
        uv_path="/usr/local/bin/uv",
    )
    assert script.count("New-ScheduledTaskTrigger -Daily -At") == 1
    assert '-At "08:00"' in script
    assert WINDOWS_TASK_NAME in script
    assert "-Force" in script
    assert '"/usr/local/bin/uv"' in script
    assert "config.yaml" in script
    assert "state/digest.db" in script


def test_build_register_task_script_multiple_times(tmp_path: Path):
    script = build_register_task_script(
        ["08:00", "20:30"],
        "claude",
        tmp_path,
        "config.yaml",
        "state/digest.db",
        uv_path="/usr/local/bin/uv",
    )
    assert script.count("New-ScheduledTaskTrigger -Daily -At") == 2
    assert '-At "08:00"' in script
    assert '-At "20:30"' in script


def test_build_register_task_script_claude_code_cli_adds_logon_type(tmp_path: Path):
    script = build_register_task_script(
        ["08:00"],
        "claude-code-cli",
        tmp_path,
        "config.yaml",
        "state/digest.db",
        uv_path="/usr/local/bin/uv",
    )
    assert "-LogonType Interactive" in script


@pytest.mark.parametrize("provider", ["claude", "local-ai"])
def test_build_register_task_script_api_provider_omits_logon_type(
    tmp_path: Path, provider: str
):
    script = build_register_task_script(
        ["08:00"], provider, tmp_path, "config.yaml", "state/digest.db", uv_path="uv"
    )
    assert "-LogonType Interactive" not in script


def test_build_register_task_script_empty_times_raises(tmp_path: Path):
    with pytest.raises(ValueError):
        build_register_task_script(
            [], "claude", tmp_path, "config.yaml", "state/digest.db", uv_path="uv"
        )


def test_windows_backend_render_includes_task_name(tmp_path: Path):
    backend = WindowsBackend(
        "Asia/Tokyo", ["08:00"], "claude", tmp_path, "config.yaml", "state/digest.db"
    )
    rendered = backend.render()
    assert WINDOWS_TASK_NAME in rendered
    assert "Register-ScheduledTask" in rendered


def test_windows_backend_install_calls_register(tmp_path: Path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "src.scheduler.windows.run_register_scheduled_task",
        lambda script: calls.append(script),
    )
    backend = WindowsBackend(
        "Asia/Tokyo", ["08:00"], "claude", tmp_path, "config.yaml", "state/digest.db"
    )
    backend.install()
    assert len(calls) == 1
    assert WINDOWS_TASK_NAME in calls[0]


def test_windows_backend_uninstall_calls_unregister(tmp_path: Path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "src.scheduler.windows.run_unregister_scheduled_task",
        lambda: calls.append("unregister"),
    )
    backend = WindowsBackend(
        "Asia/Tokyo", ["08:00"], "claude", tmp_path, "config.yaml", "state/digest.db"
    )
    backend.uninstall()
    assert calls == ["unregister"]


def test_windows_backend_status_reflects_task_existence(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "src.scheduler.windows.run_get_scheduled_task_exists", lambda: True
    )
    backend = WindowsBackend(
        "Asia/Tokyo", ["08:00"], "claude", tmp_path, "config.yaml", "state/digest.db"
    )
    assert backend.status() is True

    monkeypatch.setattr(
        "src.scheduler.windows.run_get_scheduled_task_exists", lambda: False
    )
    assert backend.status() is False


class _FakeCompletedProcess:
    def __init__(self, returncode: int, stderr: str = ""):
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = ""


def test_run_register_scheduled_task_raises_on_failure(monkeypatch):
    monkeypatch.setattr(
        "src.scheduler.windows.run_powershell",
        lambda script: _FakeCompletedProcess(1, "boom"),
    )
    with pytest.raises(RuntimeError):
        run_register_scheduled_task("dummy-script")


def test_run_unregister_scheduled_task_raises_on_failure(monkeypatch):
    monkeypatch.setattr(
        "src.scheduler.windows.run_powershell",
        lambda script: _FakeCompletedProcess(1, "boom"),
    )
    with pytest.raises(RuntimeError):
        run_unregister_scheduled_task()


def test_run_get_scheduled_task_exists_true_and_false(monkeypatch):
    monkeypatch.setattr(
        "src.scheduler.windows.run_powershell",
        lambda script: _FakeCompletedProcess(0),
    )
    assert run_get_scheduled_task_exists() is True

    monkeypatch.setattr(
        "src.scheduler.windows.run_powershell",
        lambda script: _FakeCompletedProcess(1),
    )
    assert run_get_scheduled_task_exists() is False


def test_run_powershell_invokes_subprocess(monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        return _FakeCompletedProcess(0)

    monkeypatch.setattr("subprocess.run", fake_run)
    run_powershell("Get-Date")
    assert captured["args"][0] == "powershell.exe"
    assert "-Command" in captured["args"]
