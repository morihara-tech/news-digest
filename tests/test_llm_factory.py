"""create_llm_provider() が request_importance_score を各プロバイダーへ
正しく伝播することを確認する軽量テスト。実際のAPI呼び出しは発生させない。
"""

from __future__ import annotations

from src.config import LLMConfig
from src.llm.claude_code_cli_provider import ClaudeCodeCliProvider
from src.llm.claude_provider import ClaudeProvider
from src.llm.factory import create_llm_provider
from src.llm.local_ai_provider import LocalAIProvider


def test_create_llm_provider_defaults_request_importance_score_to_false(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-dummy")
    provider = create_llm_provider(LLMConfig(provider="claude"))
    assert isinstance(provider, ClaudeProvider)
    assert provider._request_importance_score is False


def test_create_llm_provider_propagates_true_to_claude_provider(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-dummy")
    provider = create_llm_provider(LLMConfig(provider="claude"), request_importance_score=True)
    assert isinstance(provider, ClaudeProvider)
    assert provider._request_importance_score is True


def test_create_llm_provider_propagates_to_local_ai_provider():
    provider = create_llm_provider(
        LLMConfig(provider="local-ai"), request_importance_score=True
    )
    assert isinstance(provider, LocalAIProvider)
    assert provider._request_importance_score is True

    provider_default = create_llm_provider(LLMConfig(provider="local-ai"))
    assert provider_default._request_importance_score is False


def test_create_llm_provider_propagates_to_claude_code_cli_provider():
    provider = create_llm_provider(
        LLMConfig(provider="claude-code-cli"), request_importance_score=True
    )
    assert isinstance(provider, ClaudeCodeCliProvider)
    assert provider._request_importance_score is True

    provider_default = create_llm_provider(LLMConfig(provider="claude-code-cli"))
    assert provider_default._request_importance_score is False


def test_create_llm_provider_unknown_provider_raises():
    import pytest

    config = LLMConfig(provider="claude")
    config.provider = "unknown"  # type: ignore[assignment]
    with pytest.raises(ValueError):
        create_llm_provider(config)
