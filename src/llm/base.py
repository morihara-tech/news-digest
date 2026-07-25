"""LLMProvider抽象基底クラス。"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.core.models import Article


class LLMProvider(ABC):
    """記事要約を行うプロバイダーの共通インターフェース。"""

    @abstractmethod
    def summarize(self, article: Article) -> str:
        """1記事を要約して文字列を返す。失敗時は例外を送出する。"""
        raise NotImplementedError

    def summarize_batch(self, articles: list[Article]) -> dict[str, str]:
        """複数記事をまとめて要約する。デフォルト実装は1記事ずつ summarize を呼ぶ。

        1記事の要約に失敗しても他記事の処理は継続し、失敗した記事は
        結果dictに含めない（呼び出し元が縮退配信にフォールバックする）。
        """
        results: dict[str, str] = {}
        for article in articles:
            try:
                results[article.normalized_url()] = self.summarize(article)
            except Exception:  # noqa: BLE001 - 個別記事の失敗は握りつぶし縮退配信に委ねる
                continue
        return results
