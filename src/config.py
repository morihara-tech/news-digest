"""config.yaml を読み込み、pydanticモデルとしてバリデーションするモジュール。

config.example.yaml の構造をそのままモデル化している。
実運用の config.yaml は .gitignore 対象であり、README の手順に従って
config.example.yaml をコピーして作成することを前提とする。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

DEFAULT_CONFIG_PATH = Path("config.yaml")


class ClaudeCodeCliConfig(BaseModel):
    """claude-code-cli プロバイダー固有の設定。"""

    command: str = "claude"
    model: str | None = None
    timeout_seconds: int = 300
    max_retries: int = 1


class LLMConfig(BaseModel):
    provider: Literal["claude", "local-ai", "claude-code-cli"] = "claude"
    model: str | None = None
    api_key_env: str = "ANTHROPIC_API_KEY"
    base_url: str | None = None
    claude_code_cli: ClaudeCodeCliConfig = Field(default_factory=ClaudeCodeCliConfig)
    max_input_chars: int = 12000
    summary_language: str = "ja"
    summary_style: str = "3行以内・結論から"
    # コスト超過フォールバック: 1日あたりの要約対象記事数上限。
    # 超過分は要約せず縮退配信（タイトル+リンクのみ）にフォールバックする。
    max_articles_to_summarize: int = 50


class DeliveryTargetConfig(BaseModel):
    name: str
    format: Literal["slack", "google_chat"]
    webhook_url_env: str
    enabled: bool = True


class ScheduleConfig(BaseModel):
    timezone: str = "Asia/Tokyo"
    times: list[str] = Field(default_factory=lambda: ["08:00"])
    notify_on_empty: bool = True
    treat_updated_as_new: bool = False


class DigestConfig(BaseModel):
    max_articles: int = 20
    group_by: Literal["feed", "category", "none"] = "feed"


class RetentionConfig(BaseModel):
    seen_ttl_days: int = 90


class DeliveryPolicyConfig(BaseModel):
    max_retry_runs: int = 3


class FiltersConfig(BaseModel):
    include_keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    # 発行日フィルタ。指定日数より発行日が古い記事を除外する。
    # None（未指定）の場合は日付フィルタなし（後方互換の既定動作）。
    max_age_days: int | None = None


class FeedConfig(BaseModel):
    name: str
    url: str
    category: str = "general"
    enabled: bool = True
    filters: FiltersConfig | None = None

    def effective_filters(self, global_filters: FiltersConfig) -> FiltersConfig:
        """フィード単位のfiltersが指定されていればそれを優先（上書き）し、
        なければグローバルfiltersを適用する。"""
        if self.filters is not None:
            return self.filters
        return global_filters


class AppConfig(BaseModel):
    version: int = 1
    llm: LLMConfig = Field(default_factory=LLMConfig)
    delivery: list[DeliveryTargetConfig] = Field(default_factory=list)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    digest: DigestConfig = Field(default_factory=DigestConfig)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)
    delivery_policy: DeliveryPolicyConfig = Field(default_factory=DeliveryPolicyConfig)
    filters: FiltersConfig = Field(default_factory=FiltersConfig)
    feeds: list[FeedConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_feed_names_unique(self) -> "AppConfig":
        names = [f.name for f in self.feeds]
        if len(names) != len(set(names)):
            raise ValueError("feeds に重複した name があります")
        return self

    def enabled_feeds(self) -> list[FeedConfig]:
        return [f for f in self.feeds if f.enabled]

    def enabled_delivery_targets(self) -> list[DeliveryTargetConfig]:
        return [d for d in self.delivery if d.enabled]


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> AppConfig:
    """config.yaml を読み込みバリデーションする。

    存在しない場合はわかりやすいエラーメッセージを送出する。
    """
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(
            f"設定ファイルが見つかりません: {config_path}. "
            "README.md の手順に従い config.example.yaml をコピーして "
            "config.yaml を作成してください。"
        )
    with config_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return AppConfig.model_validate(raw)


def get_env(name: str) -> str | None:
    """環境変数を取得するだけの薄いラッパー（テストでモック差し替えしやすくするため）。"""
    return os.environ.get(name)
