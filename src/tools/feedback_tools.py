"""フィードバック記録系のMCPツールで使う純粋関数群。"""

from __future__ import annotations

from src.core.state import StateStore


def record_feedback(store: StateStore, url: str, feedback_type: str, value: str | None = None) -> dict:
    feedback_id = store.add_feedback(url=url, feedback_type=feedback_type, value=value)
    return {"id": feedback_id, "url": url, "feedback_type": feedback_type, "value": value}
