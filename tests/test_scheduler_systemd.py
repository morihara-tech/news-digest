from __future__ import annotations

from pathlib import Path

from src.scheduler.systemd import (
    SystemdBackend,
    build_service_unit_content,
    build_timer_unit_content,
)


def test_build_service_unit_content_references_wrapper_script(tmp_path: Path):
    script = tmp_path / "run-news-digest.sh"
    content = build_service_unit_content(script)
    assert "[Service]" in content
    assert f'ExecStart=/bin/bash "{script}"' in content
    assert "Type=oneshot" in content


def test_build_timer_unit_content_multiple_times_with_tz():
    content = build_timer_unit_content("Asia/Tokyo", ["08:00", "20:30"])
    assert "OnCalendar=*-*-* 08:00:00 Asia/Tokyo" in content
    assert "OnCalendar=*-*-* 20:30:00 Asia/Tokyo" in content
    assert "Persistent=true" in content
    assert "WantedBy=timers.target" in content


def test_systemd_backend_render_includes_both_unit_paths(tmp_path: Path):
    script = tmp_path / "run-news-digest.sh"
    backend = SystemdBackend("Asia/Tokyo", ["08:00"], script)
    rendered = backend.render()
    assert "news-digest.service" in rendered
    assert "news-digest.timer" in rendered


def test_systemd_backend_install_writes_units_and_reloads(tmp_path: Path, monkeypatch):
    unit_dir = tmp_path / "systemd-user"
    service_path = unit_dir / "news-digest.service"
    timer_path = unit_dir / "news-digest.timer"

    monkeypatch.setattr("src.scheduler.systemd.SYSTEMD_USER_DIR", unit_dir)
    monkeypatch.setattr("src.scheduler.systemd.systemd_service_path", lambda: service_path)
    monkeypatch.setattr("src.scheduler.systemd.systemd_timer_path", lambda: timer_path)

    calls = []
    monkeypatch.setattr(
        "src.scheduler.systemd.run_systemctl_daemon_reload",
        lambda: calls.append("daemon-reload"),
    )
    monkeypatch.setattr(
        "src.scheduler.systemd.run_systemctl_enable_now",
        lambda: calls.append("enable-now"),
    )

    script = tmp_path / "run-news-digest.sh"
    backend = SystemdBackend("Asia/Tokyo", ["08:00"], script)
    backend.install()

    assert service_path.exists()
    assert timer_path.exists()
    assert calls == ["daemon-reload", "enable-now"]
    assert "Asia/Tokyo" in timer_path.read_text(encoding="utf-8")


def test_systemd_backend_uninstall_removes_units(tmp_path: Path, monkeypatch):
    unit_dir = tmp_path / "systemd-user"
    unit_dir.mkdir(parents=True)
    service_path = unit_dir / "news-digest.service"
    timer_path = unit_dir / "news-digest.timer"
    service_path.write_text("dummy", encoding="utf-8")
    timer_path.write_text("dummy", encoding="utf-8")

    monkeypatch.setattr("src.scheduler.systemd.systemd_service_path", lambda: service_path)
    monkeypatch.setattr("src.scheduler.systemd.systemd_timer_path", lambda: timer_path)
    monkeypatch.setattr("src.scheduler.systemd.run_systemctl_disable_now", lambda: None)
    monkeypatch.setattr("src.scheduler.systemd.run_systemctl_daemon_reload", lambda: None)

    script = tmp_path / "run-news-digest.sh"
    backend = SystemdBackend("Asia/Tokyo", ["08:00"], script)
    backend.uninstall()

    assert not service_path.exists()
    assert not timer_path.exists()


def test_systemd_backend_status_reflects_file_presence(tmp_path: Path, monkeypatch):
    unit_dir = tmp_path / "systemd-user"
    service_path = unit_dir / "news-digest.service"
    timer_path = unit_dir / "news-digest.timer"

    monkeypatch.setattr("src.scheduler.systemd.systemd_service_path", lambda: service_path)
    monkeypatch.setattr("src.scheduler.systemd.systemd_timer_path", lambda: timer_path)

    script = tmp_path / "run-news-digest.sh"
    backend = SystemdBackend("Asia/Tokyo", ["08:00"], script)
    assert backend.status() is False

    unit_dir.mkdir(parents=True)
    service_path.write_text("dummy", encoding="utf-8")
    timer_path.write_text("dummy", encoding="utf-8")
    assert backend.status() is True
