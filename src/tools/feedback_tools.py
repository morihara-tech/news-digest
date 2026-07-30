"""フィードバック記録系のMCPツールで使う純粋関数群。"""

from __future__ import annotations

from src.core.state import StateStore


def record_feedback(store: StateStore, url: str, feedback_type: str, value: str | None = None) -> dict:
    """フィードバックを記録する。feedback_type は store 側で正規化(strip+lower)されるため、
    戻り値にも正規化後の値を反映する。"""
    normalized_type = feedback_type.strip().lower()
    feedback_id = store.add_feedback(url=url, feedback_type=feedback_type, value=value)
    return {"id": feedback_id, "url": url, "feedback_type": normalized_type, "value": value}
