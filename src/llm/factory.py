"""config.llm.provider の値に応じてLLMProviderを生成するファクトリ。"""

from __future__ import annotations

from src.config import LLMConfig
from src.llm.base import LLMProvider


def create_llm_provider(config: LLMConfig, request_importance_score: bool = False) -> LLMProvider:
    if config.provider == "claude":
        from src.llm.claude_provider import ClaudeProvider

        return ClaudeProvider(config, request_importance_score=request_importance_score)
    if config.provider == "local-ai":
        from src.llm.local_ai_provider import LocalAIProvider

        return LocalAIProvider(config, request_importance_score=request_importance_score)
    if config.provider == "claude-code-cli":
        from src.llm.claude_code_cli_provider import ClaudeCodeCliProvider

        return ClaudeCodeCliProvider(config, request_importance_score=request_importance_score)
    raise ValueError(f"未知のLLMプロバイダーです: {config.provider}")
