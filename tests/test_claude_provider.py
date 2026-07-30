"""ClaudeProvider（Anthropic API）のユニットテスト。

anthropic SDKクライアントの実呼び出しは行わず、
self._client.messages.create をmonkeypatchで差し替えて検証する。
"""

from __future__ import annotations

import json

from src.config import LLMConfig
from src.core.models import Article
from src.llm.base import SummaryResult
from src.llm.claude_provider import ClaudeProvider


class FakeTextBlock:
    def __init__(self, text: str):
        self.type = "text"
        self.text = text


class FakeMessage:
    def __init__(self, text: str):
        self.content = [FakeTextBlock(text)]


def _provider(monkeypatch, request_importance_score: bool = False) -> ClaudeProvider:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-dummy")
    config = LLMConfig(provider="claude")
    return ClaudeProvider(config, request_importance_score=request_importance_score)


def _article() -> Article:
    return Article(
        url="https://example.com/a",
        title="Title A",
        feed_name="feed",
        summary_source="body a",
    )


def test_summarize_with_score_request_parses_json_response(monkeypatch):
    provider = _provider(monkeypatch, request_importance_score=True)
    response_text = json.dumps({"summary": "要約A", "score": 75}, ensure_ascii=False)
    monkeypatch.setattr(
        provider._client.messages, "create", lambda **kwargs: FakeMessage(response_text)
    )

    result = provider.summarize(_article())
    assert result == SummaryResult(summary="要約A", importance_score=75.0)


def test_summarize_with_score_request_missing_score_key_falls_back_to_none(monkeypatch):
    provider = _provider(monkeypatch, request_importance_score=True)
    response_text = json.dumps({"summary": "要約A"}, ensure_ascii=False)
    monkeypatch.setattr(
        provider._client.messages, "create", lambda **kwargs: FakeMessage(response_text)
    )

    result = provider.summarize(_article())
    assert result == SummaryResult(summary="要約A", importance_score=None)


def test_summarize_with_score_request_non_json_response_falls_back_to_full_text(monkeypatch):
    provider = _provider(monkeypatch, request_importance_score=True)
    response_text = "これはJSONではないプレーンな要約です。"
    monkeypatch.setattr(
        provider._client.messages, "create", lambda **kwargs: FakeMessage(response_text)
    )

    result = provider.summarize(_article())
    assert result == SummaryResult(summary=response_text, importance_score=None)


def test_summarize_without_score_request_uses_plain_prompt(monkeypatch):
    provider = _provider(monkeypatch, request_importance_score=False)
    response_text = "プレーンな要約テキスト"
    captured_kwargs = {}

    def fake_create(**kwargs):
        captured_kwargs.update(kwargs)
        return FakeMessage(response_text)

    monkeypatch.setattr(provider._client.messages, "create", fake_create)

    result = provider.summarize(_article())
    assert result == SummaryResult(summary=response_text, importance_score=None)
    prompt = captured_kwargs["messages"][0]["content"]
    assert "score" not in prompt
    assert "0〜100" not in prompt
