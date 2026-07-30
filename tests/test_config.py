from __future__ import annotations

import pytest
import yaml

from src.config import AppConfig, ScoringConfig, ScoringFeedbackConfig, load_config


def test_load_config_example_yaml_is_valid():
    config = load_config("config.example.yaml")
    assert config.llm.provider == "claude"
    assert len(config.feeds) == 2
    assert config.digest.max_articles == 20
    assert config.retention.seen_ttl_days == 90


def test_load_config_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "does-not-exist.yaml")


def test_feed_effective_filters_overrides_global():
    raw = yaml.safe_load(
        """
        feeds:
          - name: a
            url: https://example.com/a
            filters:
              include_keywords: ["AWS"]
          - name: b
            url: https://example.com/b
        filters:
          include_keywords: []
          exclude_keywords: ["ad"]
        """
    )
    config = AppConfig.model_validate(raw)
    feed_a, feed_b = config.feeds
    assert feed_a.effective_filters(config.filters).include_keywords == ["AWS"]
    assert feed_b.effective_filters(config.filters).exclude_keywords == ["ad"]


def test_duplicate_feed_names_rejected():
    raw = {
        "feeds": [
            {"name": "dup", "url": "https://example.com/a"},
            {"name": "dup", "url": "https://example.com/b"},
        ]
    }
    with pytest.raises(ValueError):
        AppConfig.model_validate(raw)


def test_scraper_source_type_requires_scraper_id():
    raw = {
        "feeds": [
            {"name": "no-scraper-id", "url": "https://example.com/blog", "source_type": "scraper"},
        ]
    }
    with pytest.raises(ValueError):
        AppConfig.model_validate(raw)


def test_scraper_source_type_with_scraper_id_is_valid():
    raw = {
        "feeds": [
            {
                "name": "example-blog",
                "url": "https://example.com/blog",
                "source_type": "scraper",
                "scraper_id": "example-blog",
            },
        ]
    }
    config = AppConfig.model_validate(raw)
    assert config.feeds[0].source_type == "scraper"
    assert config.feeds[0].scraper_id == "example-blog"


def test_scoring_feedback_config_defaults():
    feedback = ScoringFeedbackConfig()
    assert feedback.good_weight == 10.0
    assert feedback.bad_weight == 10.0
    assert feedback.mute_penalty == 1000.0
    assert feedback.saturation_count == 5
    assert feedback.max_total_delta == 40.0
    assert feedback.mute_min_count == 1
    assert feedback.keywords == []
    assert feedback.lookback_days is None


def test_scoring_config_defaults():
    scoring = ScoringConfig()
    assert scoring.enabled is True
    assert scoring.emphasis_threshold == 70.0
    assert scoring.emphasis_marker == "⭐"
    assert scoring.default_score == 50.0
    assert scoring.score_min == 0.0
    assert scoring.score_max == 100.0
    assert isinstance(scoring.feedback, ScoringFeedbackConfig)


def test_app_config_without_scoring_block_uses_defaults():
    """既存の config.yaml に scoring ブロックがなくても後方互換で動作すること。"""
    raw = {
        "feeds": [
            {"name": "a", "url": "https://example.com/a"},
        ]
    }
    config = AppConfig.model_validate(raw)
    assert config.scoring == ScoringConfig()


def test_scoring_score_min_gte_score_max_raises():
    raw = {"scoring": {"score_min": 100.0, "score_max": 50.0}}
    with pytest.raises(ValueError):
        AppConfig.model_validate(raw)


def test_scoring_score_min_equal_score_max_raises():
    raw = {"scoring": {"score_min": 50.0, "score_max": 50.0}}
    with pytest.raises(ValueError):
        AppConfig.model_validate(raw)


def test_load_config_example_yaml_has_scoring_defaults():
    config = load_config("config.example.yaml")
    assert config.scoring.enabled is True
    assert config.scoring.emphasis_threshold == 70.0
    assert config.scoring.emphasis_marker == "⭐"
    assert config.scoring.default_score == 50.0
    assert config.scoring.score_min == 0.0
    assert config.scoring.score_max == 100.0
    assert config.scoring.feedback.good_weight == 10.0
    assert config.scoring.feedback.bad_weight == 10.0
    assert config.scoring.feedback.mute_penalty == 1000.0
    assert config.scoring.feedback.saturation_count == 5
    assert config.scoring.feedback.max_total_delta == 40.0
    assert config.scoring.feedback.mute_min_count == 1
    assert config.scoring.feedback.keywords == []
    assert config.scoring.feedback.lookback_days is None
