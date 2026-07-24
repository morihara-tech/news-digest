"""config.llm.provider の値に応じてLLMProviderを生成するファクトリ。"""

from __future__ import annotations

from src.config import LLMConfig
from src.llm.base import LLMProvider


def create_llm_provider(config: LLMConfig) -> LLMProvider:
    if config.provider == "claude":
        from src.llm.claude_provider import ClaudeProvider

        return ClaudeProvider(config)
    if config.provider == "local-ai":
        from src.llm.local_ai_provider import LocalAIProvider

        return LocalAIProvider(config)
    if config.provider == "claude-code-cli":
        from src.llm.claude_code_cli_provider import ClaudeCodeCliProvider

        return ClaudeCodeCliProvider(config)
    raise ValueError(f"未知のLLMプロバイダーです: {config.provider}")
