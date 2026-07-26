from __future__ import annotations

import pytest
import yaml

from src.config import AppConfig, load_config


def test_load_config_example_yaml_is_valid():
    config = load_config("config.example.yaml")
    assert config.llm.provider == "claude"
    assert len(config.feeds) == 1
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
