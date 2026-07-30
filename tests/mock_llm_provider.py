"""テスト用のLLMProviderモック実装。外部呼び出し・課金を一切発生させない。"""

from __future__ import annotations

from src.core.models import Article
from src.llm.base import LLMProvider, SummaryResult


class MockLLMProvider(LLMProvider):
    """常に固定文字列を返すモック。

    - fail_urls に含まれるURLは要約失敗として扱う。
    - raise_on_batch=True の場合、summarize_batch() 呼び出し全体が例外を送出する。
    - raise_on_batch_for_feeds に含まれる feed_name の記事群が summarize_batch() に
      渡された場合のみ、その呼び出し全体が例外を送出する
      （サイトごとの想定外エラーをシミュレートするため）。
    - scores に url→スコアを指定すると、summarize()/summarize_batch() の
      SummaryResult.importance_score にそのスコアが設定される
      （追加のLLM呼び出しなしで要約とスコアを同時に取得できることを模す）。
    """

    def __init__(
        self,
        fail_urls: set[str] | None = None,
        raise_on_batch: bool = False,
        raise_on_batch_for_feeds: set[str] | None = None,
        scores: dict[str, float] | None = None,
    ):
        self.fail_urls = fail_urls or set()
        self.raise_on_batch = raise_on_batch
        self.raise_on_batch_for_feeds = raise_on_batch_for_feeds or set()
        self.scores = scores
        self.summarize_calls: list[str] = []

    def summarize(self, article: Article) -> SummaryResult:
        self.summarize_calls.append(article.normalized_url())
        if article.normalized_url() in self.fail_urls:
            raise RuntimeError("mock summarize failure")
        return SummaryResult(
            summary=f"要約: {article.title}",
            importance_score=self.scores.get(article.normalized_url()) if self.scores else None,
        )

    def summarize_batch(self, articles: list[Article]) -> dict[str, SummaryResult]:
        if self.raise_on_batch:
            raise RuntimeError("mock batch failure")
        if articles and any(a.feed_name in self.raise_on_batch_for_feeds for a in articles):
            raise RuntimeError("mock batch failure for feed")
        results: dict[str, SummaryResult] = {}
        for article in articles:
            self.summarize_calls.append(article.normalized_url())
            if article.normalized_url() in self.fail_urls:
                continue
            results[article.normalized_url()] = SummaryResult(
                summary=f"要約: {article.title}",
                importance_score=(
                    self.scores.get(article.normalized_url()) if self.scores else None
                ),
            )
        return results
