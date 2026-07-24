from __future__ import annotations

import json
import subprocess

import pytest

from src.config import ClaudeCodeCliConfig, LLMConfig
from src.core.models import Article
from src.llm.claude_code_cli_provider import (
    ClaudeCodeCliProvider,
    ClaudeCodeCliResponseError,
    _minimal_subprocess_env,
)


def _config(**overrides) -> LLMConfig:
    cli_config = ClaudeCodeCliConfig(
        command="claude", timeout_seconds=5, max_retries=overrides.pop("max_retries", 1)
    )
    return LLMConfig(provider="claude-code-cli", claude_code_cli=cli_config, **overrides)


def _articles() -> list[Article]:
    return [
        Article(url="https://example.com/a", title="Title A", feed_name="feed", summary_source="body a"),
        Article(url="https://example.com/b", title="Title B", feed_name="feed", summary_source="body b"),
    ]


class FakeCompletedProcess:
    def __init__(self, stdout: str, returncode: int = 0, stderr: str = ""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


def test_minimal_subprocess_env_excludes_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("PATH", "/usr/bin")
    env = _minimal_subprocess_env()
    assert "ANTHROPIC_API_KEY" not in env
    assert env.get("PATH") == "/usr/bin"


def test_summarize_batch_two_stage_json_parse_success(monkeypatch):
    provider = ClaudeCodeCliProvider(_config())
    inner = json.dumps(
        {"https://example.com/a": "要約A", "https://example.com/b": "要約B"}, ensure_ascii=False
    )
    top_level = json.dumps({"result": inner}, ensure_ascii=False)

    def fake_run(cmd, capture_output, text, timeout, env, check):
        assert "--tools" in cmd
        tools_index = cmd.index("--tools")
        assert cmd[tools_index + 1] == ""
        assert "-p" in cmd
        assert "ANTHROPIC_API_KEY" not in env
        return FakeCompletedProcess(stdout=top_level)

    monkeypatch.setattr(subprocess, "run", fake_run)

    results = provider.summarize_batch(_articles())
    assert results == {"https://example.com/a": "要約A", "https://example.com/b": "要約B"}


def test_summarize_batch_handles_markdown_fenced_json(monkeypatch):
    provider = ClaudeCodeCliProvider(_config())
    inner_text = "説明文です。\n```json\n{\"https://example.com/a\": \"要約A\"}\n```\n"
    top_level = json.dumps({"result": inner_text}, ensure_ascii=False)

    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: FakeCompletedProcess(stdout=top_level)
    )
    results = provider.summarize_batch([_articles()[0]])
    assert results == {"https://example.com/a": "要約A"}


def test_summarize_batch_retries_on_timeout_then_succeeds(monkeypatch):
    provider = ClaudeCodeCliProvider(_config(max_retries=1))
    inner = json.dumps({"https://example.com/a": "要約A", "https://example.com/b": "要約B"})
    top_level = json.dumps({"result": inner})

    calls = {"count": 0}

    def fake_run(cmd, capture_output, text, timeout, env, check):
        calls["count"] += 1
        if calls["count"] == 1:
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)
        return FakeCompletedProcess(stdout=top_level)

    monkeypatch.setattr(subprocess, "run", fake_run)
    results = provider.summarize_batch(_articles())
    assert calls["count"] == 2
    assert results["https://example.com/a"] == "要約A"


def test_summarize_batch_raises_after_exhausting_retries(monkeypatch):
    provider = ClaudeCodeCliProvider(_config(max_retries=1))

    def fake_run(cmd, capture_output, text, timeout, env, check):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(RuntimeError):
        provider.summarize_batch(_articles())


def test_summarize_batch_raises_on_invalid_top_level_json(monkeypatch):
    provider = ClaudeCodeCliProvider(_config(max_retries=0))
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: FakeCompletedProcess(stdout="not json at all")
    )
    with pytest.raises(RuntimeError):
        provider.summarize_batch(_articles())


def test_summarize_batch_raises_on_nonzero_exit_code(monkeypatch):
    provider = ClaudeCodeCliProvider(_config(max_retries=0))
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: FakeCompletedProcess(stdout="", returncode=1, stderr="boom"),
    )
    with pytest.raises(RuntimeError):
        provider.summarize_batch(_articles())


def test_summarize_batch_empty_articles_returns_empty_dict():
    provider = ClaudeCodeCliProvider(_config())
    assert provider.summarize_batch([]) == {}
