"""Ollama等のOpenAI互換APIを利用した要約プロバイダー。"""

from __future__ import annotations

import httpx

from src.config import LLMConfig
from src.core.models import Article
from src.llm.base import LLMProvider

DEFAULT_BASE_URL = "http://localhost:11434/v1"
DEFAULT_MODEL = "llama3"


class LocalAIProvider(LLMProvider):
    def __init__(self, config: LLMConfig):
        self._base_url = (config.base_url or DEFAULT_BASE_URL).rstrip("/")
        self._model = config.model or DEFAULT_MODEL
        self._max_input_chars = config.max_input_chars
        self._language = config.summary_language
        self._style = config.summary_style

    def summarize(self, article: Article) -> str:
        text = article.summary_source[: self._max_input_chars]
        prompt = (
            f"以下のニュース記事を{self._language}で要約してください。"
            f"スタイル: {self._style}\n\n"
            f"タイトル: {article.title}\n"
            f"本文: {text}"
        )
        response = httpx.post(
            f"{self._base_url}/chat/completions",
            json={
                "model": self._model,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60.0,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()
