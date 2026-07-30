"""LocalAIProvider（Ollama等OpenAI互換API）のユニットテスト。

httpx.post をmonkeypatchで差し替え、実際のHTTP通信は発生させない。
"""

from __future__ import annotations

import json

import httpx

from src.config import LLMConfig
from src.core.models import Article
from src.llm.base import SummaryResult
from src.llm.local_ai_provider import LocalAIProvider


class FakeResponse:
    def __init__(self, content: str):
        self._content = content

    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


def _provider(request_importance_score: bool = False) -> LocalAIProvider:
    config = LLMConfig(provider="local-ai")
    return LocalAIProvider(config, request_importance_score=request_importance_score)


def _article() -> Article:
    return Article(
        url="https://example.com/a",
        title="Title A",
        feed_name="feed",
        summary_source="body a",
    )


def test_summarize_with_score_request_parses_json_response(monkeypatch):
    provider = _provider(request_importance_score=True)
    response_text = json.dumps({"summary": "要約A", "score": 60}, ensure_ascii=False)
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResponse(response_text))

    result = provider.summarize(_article())
    assert result == SummaryResult(summary="要約A", importance_score=60.0)


def test_summarize_with_score_request_missing_score_key_falls_back_to_none(monkeypatch):
    provider = _provider(request_importance_score=True)
    response_text = json.dumps({"summary": "要約A"}, ensure_ascii=False)
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResponse(response_text))

    result = provider.summarize(_article())
    assert result == SummaryResult(summary="要約A", importance_score=None)


def test_summarize_with_score_request_non_json_response_falls_back_to_full_text(monkeypatch):
    provider = _provider(request_importance_score=True)
    response_text = "これはJSONではないプレーンな要約です。"
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResponse(response_text))

    result = provider.summarize(_article())
    assert result == SummaryResult(summary=response_text, importance_score=None)


def test_summarize_without_score_request_uses_plain_prompt(monkeypatch):
    provider = _provider(request_importance_score=False)
    response_text = "プレーンな要約テキスト"
    captured_kwargs = {}

    def fake_post(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return FakeResponse(response_text)

    monkeypatch.setattr(httpx, "post", fake_post)

    result = provider.summarize(_article())
    assert result == SummaryResult(summary=response_text, importance_score=None)
    prompt = captured_kwargs["json"]["messages"][0]["content"]
    assert "score" not in prompt
    assert "0〜100" not in prompt
