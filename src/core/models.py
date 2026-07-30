"""コア層で共有するデータモデル。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Article:
    """フィードから取得した1記事。URLをユニークキーとする。"""

    url: str
    title: str
    feed_name: str
    category: str = "general"
    summary_source: str = ""  # 要約前の本文抜粋（RSSのdescription等）
    published_at: str | None = None  # 表示・ログ用の生文字列（feedparserの生値）
    published_parsed: datetime | None = None  # 発行日時のパース結果（UTC aware、フィルタ用）
    summary: str | None = None  # LLMによる要約結果（未設定なら縮退配信）
    degraded: bool = False  # True の場合、要約なしで縮退配信する
    degraded_reason: str | None = None
    llm_importance_score: float | None = None  # digest層が設定するLLM生スコア（後続タスクで使用）
    importance_score: float | None = None      # scoring層が設定する最終スコア（delivery/sortが参照。後続タスクで使用）
    emphasized: bool = False                    # scoring層が確定する強調フラグ（後続タスクで使用）

    def normalized_url(self) -> str:
        """URLの正規化。最低限そのまま文字列で一意化するが、
        末尾スラッシュの揺れなど明らかな表記ゆれのみ吸収する。"""
        return self.url.strip()
