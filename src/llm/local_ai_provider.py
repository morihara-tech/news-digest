"""Ollama等のOpenAI互換APIを利用した要約プロバイダー。"""

from __future__ import annotations

import httpx

from src.config import LLMConfig
from src.core.models import Article
from src.llm.base import LLMProvider, SummaryResult, parse_summary_json

DEFAULT_BASE_URL = "http://localhost:11434/v1"
DEFAULT_MODEL = "llama3"


class LocalAIProvider(LLMProvider):
    def __init__(self, config: LLMConfig, request_importance_score: bool = False):
        self._base_url = (config.base_url or DEFAULT_BASE_URL).rstrip("/")
        self._model = config.model or DEFAULT_MODEL
        self._max_input_chars = config.max_input_chars
        self._language = config.summary_language
        self._style = config.summary_style
        self._request_importance_score = request_importance_score

    def summarize(self, article: Article) -> SummaryResult:
        text = article.summary_source[: self._max_input_chars]
        if self._request_importance_score:
            prompt = (
                f"以下のニュース記事を{self._language}で要約してください。"
                f"スタイル: {self._style}\n"
                "また、このニュースの重要度を0〜100の数値で評価してください。"
                "出力は次のJSON形式のみとし、説明文やコードフェンスは含めないでください: "
                '{"summary": "要約文字列", "score": <0-100の数値>}\n\n'
                f"タイトル: {article.title}\n"
                f"本文: {text}"
            )
        else:
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
        raw_text = data["choices"][0]["message"]["content"].strip()
        return parse_summary_json(
            raw_text, request_importance_score=self._request_importance_score
        )
