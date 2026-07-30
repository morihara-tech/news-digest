"""LLMProvider抽象基底クラス。"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass

from src.core.models import Article


@dataclass
class SummaryResult:
    """LLM呼び出し1回分の結果。要約文字列と、同一呼び出しで取得した重要度スコアを保持する。

    importance_score は LLM応答がJSONでない場合や score キーが欠落・パース不能な場合に
    None にフォールバックする（後方互換パーサの仕様。src/llm/*.py の各プロバイダー実装参照）。
    Article への反映は本モジュールの責務ではなく、呼び出し元（後続タスク）が行う。
    """

    summary: str
    importance_score: float | None = None


class LLMProvider(ABC):
    """記事要約を行うプロバイダーの共通インターフェース。"""

    @abstractmethod
    def summarize(self, article: Article) -> SummaryResult:
        """1記事を要約して SummaryResult を返す。失敗時は例外を送出する。"""
        raise NotImplementedError

    def summarize_batch(self, articles: list[Article]) -> dict[str, SummaryResult]:
        """複数記事をまとめて要約する。デフォルト実装は1記事ずつ summarize を呼ぶ。

        1記事の要約に失敗しても他記事の処理は継続し、失敗した記事は
        結果dictに含めない（呼び出し元が縮退配信にフォールバックする）。
        """
        results: dict[str, SummaryResult] = {}
        for article in articles:
            try:
                results[article.normalized_url()] = self.summarize(article)
            except Exception:  # noqa: BLE001 - 個別記事の失敗は握りつぶし縮退配信に委ねる
                continue
        return results


def coerce_score(raw: object) -> float | None:
    """score値をfloatへ変換する。数値変換できない場合はNoneにフォールバックする。"""
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def parse_summary_json(text: str, *, request_importance_score: bool) -> SummaryResult:
    """LLMの単発summarize()応答をパースする後方互換パーサ。

    - request_importance_score=False の場合はスコアを要求しないプレーン応答を想定し、
      応答全文をそのままsummaryとして扱う（importance_score=None）。
    - request_importance_score=True の場合は `{"summary": ..., "score": <0-100>}` 形式の
      JSONを期待するが、以下のいずれの場合も例外を送出せずimportance_score=Noneに
      フォールバックする:
        - 応答がJSONとしてパースできない（例: プレーンテキストが返ってきた）
        - JSONだが辞書ではない
        - JSONだが summary キーが欠落・非文字列（この場合は応答全文をsummaryとして扱う）
        - JSONだが score キーが欠落、または数値に変換できない
    """
    stripped = text.strip()
    if not request_importance_score:
        return SummaryResult(summary=stripped, importance_score=None)

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return SummaryResult(summary=stripped, importance_score=None)

    if not isinstance(parsed, dict):
        return SummaryResult(summary=stripped, importance_score=None)

    summary_value = parsed.get("summary")
    summary = summary_value if isinstance(summary_value, str) and summary_value else stripped
    score = coerce_score(parsed.get("score"))
    return SummaryResult(summary=summary, importance_score=score)
