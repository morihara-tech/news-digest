"""フィードバック学習: 蓄積されたfeedbackから重要度スコアへの補正値を集計する。

ここでは「どのfeed/keywordを優遇・冷遇・ミュートすべきか」の集合を算出するのみ
（実際のスコアへの適用は後続の重要度スコアリング側の責務）。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FeedbackWeights:
    feed_delta: dict[str, float]
    keyword_delta: dict[str, float]
    muted_feeds: set[str]
    muted_keywords: set[str]


def _compute_delta(
    good_count: int, bad_count: int, good_weight: float, bad_weight: float, saturation_count: int
) -> float:
    """good/bad件数からdeltaを計算する。

    net = good_count - bad_count
    delta = sign(net) * min(|net|, saturation_count) / saturation_count * (good_weight if net>0 else bad_weight)
    """
    net = good_count - bad_count
    if net == 0:
        return 0.0
    if saturation_count <= 0:
        return 0.0

    magnitude = min(abs(net), saturation_count) / saturation_count
    if net > 0:
        return magnitude * good_weight
    return -magnitude * bad_weight


@dataclass
class _Counter:
    good: int = 0
    bad: int = 0
    mute: int = 0


def compute_feedback_weights(store, scoring_config) -> FeedbackWeights:
    """フィードバック履歴を集計し、feed軸・keyword軸の補正値とミュート集合を返す。"""
    feedback_config = scoring_config.feedback
    rows = store.get_feedback_context(lookback_days=feedback_config.lookback_days)

    # --- フィード軸の集計 -------------------------------------------------
    feed_counters: dict[str, _Counter] = {}
    for row in rows:
        feed_name = row["feed_name"]
        feedback_type = row["feedback_type"]
        if feed_name is None or feedback_type not in ("good", "bad", "mute"):
            continue
        counter = feed_counters.setdefault(feed_name, _Counter())
        if feedback_type == "good":
            counter.good += 1
        elif feedback_type == "bad":
            counter.bad += 1
        else:
            counter.mute += 1

    feed_delta: dict[str, float] = {}
    muted_feeds: set[str] = set()
    for feed_name, counter in feed_counters.items():
        feed_delta[feed_name] = _compute_delta(
            counter.good,
            counter.bad,
            feedback_config.good_weight,
            feedback_config.bad_weight,
            feedback_config.saturation_count,
        )
        if counter.mute >= feedback_config.mute_min_count:
            muted_feeds.add(feed_name)

    # --- キーワード軸の集計 -------------------------------------------------
    keyword_delta: dict[str, float] = {}
    muted_keywords: set[str] = set()

    for keyword in feedback_config.keywords:
        keyword_lower = keyword.lower()
        counter = _Counter()
        for row in rows:
            title = row["title"]
            feedback_type = row["feedback_type"]
            if title is None or feedback_type not in ("good", "bad", "mute"):
                continue
            if keyword_lower not in title.lower():
                continue
            if feedback_type == "good":
                counter.good += 1
            elif feedback_type == "bad":
                counter.bad += 1
            else:
                counter.mute += 1

        keyword_delta[keyword] = _compute_delta(
            counter.good,
            counter.bad,
            feedback_config.good_weight,
            feedback_config.bad_weight,
            feedback_config.saturation_count,
        )
        if counter.mute >= feedback_config.mute_min_count:
            muted_keywords.add(keyword)

    return FeedbackWeights(
        feed_delta=feed_delta,
        keyword_delta=keyword_delta,
        muted_feeds=muted_feeds,
        muted_keywords=muted_keywords,
    )
