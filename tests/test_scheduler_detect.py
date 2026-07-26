from __future__ import annotations

import pytest

from src.scheduler.detect import (
    BACKEND_CRON,
    BACKEND_LAUNCHD,
    BACKEND_SYSTEMD,
    detect_backend,
    is_systemd_user_instance_available,
)


def test_detect_backend_with_override_returns_override():
    assert detect_backend("cron") == BACKEND_CRON
    assert detect_backend("systemd") == BACKEND_SYSTEMD
    assert detect_backend("launchd") == BACKEND_LAUNCHD


def test_detect_backend_with_invalid_override_raises():
    with pytest.raises(ValueError):
        detect_backend("unknown-scheduler")


def test_detect_backend_darwin_returns_launchd(monkeypatch):
    monkeypatch.setattr("src.scheduler.detect.get_platform_system", lambda: "Darwin")
    assert detect_backend(None) == BACKEND_LAUNCHD


def test_detect_backend_linux_with_systemd_available_returns_systemd(monkeypatch):
    monkeypatch.setattr("src.scheduler.detect.get_platform_system", lambda: "Linux")
    monkeypatch.setattr(
        "src.scheduler.detect.is_systemd_user_instance_available", lambda: True
    )
    assert detect_backend(None) == BACKEND_SYSTEMD


def test_detect_backend_linux_without_systemd_falls_back_to_cron(monkeypatch):
    monkeypatch.setattr("src.scheduler.detect.get_platform_system", lambda: "Linux")
    monkeypatch.setattr(
        "src.scheduler.detect.is_systemd_user_instance_available", lambda: False
    )
    assert detect_backend(None) == BACKEND_CRON


def test_detect_backend_unsupported_os_raises(monkeypatch):
    monkeypatch.setattr("src.scheduler.detect.get_platform_system", lambda: "Windows")
    with pytest.raises(ValueError):
        detect_backend(None)


def test_is_systemd_user_instance_available_false_without_systemctl(monkeypatch):
    monkeypatch.setattr("src.scheduler.detect.is_systemctl_available", lambda: False)
    assert is_systemd_user_instance_available() is False


def test_is_systemd_user_instance_available_false_without_xdg_runtime_dir(
    monkeypatch,
):
    monkeypatch.setattr("src.scheduler.detect.is_systemctl_available", lambda: True)
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    assert is_systemd_user_instance_available() is False


def test_is_systemd_user_instance_available_true_when_status_succeeds(monkeypatch):
    monkeypatch.setattr("src.scheduler.detect.is_systemctl_available", lambda: True)
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    monkeypatch.setattr("src.scheduler.detect.run_systemctl_user_status", lambda: 0)
    assert is_systemd_user_instance_available() is True


def test_is_systemd_user_instance_available_false_when_status_fails(monkeypatch):
    monkeypatch.setattr("src.scheduler.detect.is_systemctl_available", lambda: True)
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    monkeypatch.setattr("src.scheduler.detect.run_systemctl_user_status", lambda: 1)
    assert is_systemd_user_instance_available() is False
