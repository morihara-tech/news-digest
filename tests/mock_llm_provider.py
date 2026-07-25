"""テスト用のLLMProviderモック実装。外部呼び出し・課金を一切発生させない。"""

from __future__ import annotations

from src.core.models import Article
from src.llm.base import LLMProvider


class MockLLMProvider(LLMProvider):
    """常に固定文字列を返すモック。fail_urls に含まれるURLは要約失敗として扱う。"""

    def __init__(self, fail_urls: set[str] | None = None, raise_on_batch: bool = False):
        self.fail_urls = fail_urls or set()
        self.raise_on_batch = raise_on_batch
        self.summarize_calls: list[str] = []

    def summarize(self, article: Article) -> str:
        self.summarize_calls.append(article.normalized_url())
        if article.normalized_url() in self.fail_urls:
            raise RuntimeError("mock summarize failure")
        return f"要約: {article.title}"

    def summarize_batch(self, articles: list[Article]) -> dict[str, str]:
        if self.raise_on_batch:
            raise RuntimeError("mock batch failure")
        results: dict[str, str] = {}
        for article in articles:
            self.summarize_calls.append(article.normalized_url())
            if article.normalized_url() in self.fail_urls:
                continue
            results[article.normalized_url()] = f"要約: {article.title}"
        return results
