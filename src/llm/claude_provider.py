"""Anthropic API (Claude) を利用した要約プロバイダー。"""

from __future__ import annotations

from src.config import LLMConfig, get_env
from src.core.models import Article
from src.llm.base import LLMProvider, SummaryResult, parse_summary_json

DEFAULT_MODEL = "claude-sonnet-4-20250514"


class ClaudeProvider(LLMProvider):
    def __init__(self, config: LLMConfig, request_importance_score: bool = False):
        api_key = get_env(config.api_key_env)
        if not api_key:
            raise RuntimeError(
                f"環境変数 {config.api_key_env} が設定されていません。"
                ".env に ANTHROPIC_API_KEY を設定してください。"
            )
        import anthropic  # 遅延importでテスト時の依存を減らす

        self._client = anthropic.Anthropic(api_key=api_key)
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
        response = self._client.messages.create(
            model=self._model,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        ).strip()
        return parse_summary_json(
            raw_text, request_importance_score=self._request_importance_score
        )
