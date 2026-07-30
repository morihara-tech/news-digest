"""手動実行系のMCPツールで使う純粋関数群。"""

from __future__ import annotations

from dataclasses import asdict

from src.config import AppConfig
from src.core.runner import RunResult, run_digest
from src.core.state import StateStore
from src.llm.factory import create_llm_provider


def trigger_manual_run(config: AppConfig, store: StateStore) -> dict:
    """設定に従いLLMProviderを生成し、配信バッチを1回実行する。"""
    llm_provider = create_llm_provider(
        config.llm, request_importance_score=config.scoring.enabled
    )
    result: RunResult = run_digest(config, store, llm_provider)
    return asdict(result)
