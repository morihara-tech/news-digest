from __future__ import annotations

import httpx

from src.config import (
    AppConfig,
    DeliveryTargetConfig,
    DigestConfig,
    FeedConfig,
    LLMConfig,
    RetentionConfig,
    ScheduleConfig,
)
from src.core.runner import run_digest
from src.core.state import StateStore
from tests.mock_llm_provider import MockLLMProvider


def _config_with_feed(fixtures_dir, **overrides) -> AppConfig:
    feed_url = str(fixtures_dir / "rss_tech.xml")
    return AppConfig(
        llm=LLMConfig(),
        delivery=[
            DeliveryTargetConfig(
                name="my-slack",
                format="slack",
                webhook_url_env="SLACK_WEBHOOK_URL",
                enabled=True,
            )
        ],
        schedule=ScheduleConfig(notify_on_empty=True),
        digest=overrides.get("digest", DigestConfig(max_articles=20, group_by="feed")),
        retention=RetentionConfig(seen_ttl_days=90),
        feeds=[FeedConfig(name="Tech", url=feed_url, category="tech")],
    )


def _config_with_two_feeds(fixtures_dir, second_feed_file: str, second_feed_name: str, **overrides) -> AppConfig:
    tech_url = str(fixtures_dir / "rss_tech.xml")
    second_url = str(fixtures_dir / second_feed_file)
    return AppConfig(
        llm=LLMConfig(),
        delivery=[
            DeliveryTargetConfig(
                name="my-slack",
                format="slack",
                webhook_url_env="SLACK_WEBHOOK_URL",
                enabled=True,
            )
        ],
        schedule=ScheduleConfig(notify_on_empty=True),
        digest=overrides.get("digest", DigestConfig(max_articles=20, group_by="feed")),
        retention=RetentionConfig(seen_ttl_days=90),
        feeds=[
            FeedConfig(name="Tech", url=tech_url, category="tech"),
            FeedConfig(name=second_feed_name, url=second_url, category="tech"),
        ],
    )


def test_run_digest_delivers_new_articles(tmp_path, fixtures_dir, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example.com/slack")

    class FakeResponse:
        def raise_for_status(self):
            return None

    monkeypatch.setattr(httpx, "post", lambda url, json, timeout: FakeResponse())

    config = _config_with_feed(fixtures_dir)
    with StateStore(tmp_path / "digest.db") as store:
        provider = MockLLMProvider()
        result = run_digest(config, store, provider)

        assert result.status == "delivered"
        assert result.article_count == 3
        assert result.delivered_targets == ["my-slack"]

        # 配信成功後にのみdelivered_atが確定していることを確認
        rows = store.get_seen_articles()
        assert len(rows) == 3
        assert all(row["delivered_at"] is not None for row in rows)


def test_run_digest_second_run_skips_already_delivered(tmp_path, fixtures_dir, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example.com/slack")

    class FakeResponse:
        def raise_for_status(self):
            return None

    monkeypatch.setattr(httpx, "post", lambda url, json, timeout: FakeResponse())

    config = _config_with_feed(fixtures_dir)
    with StateStore(tmp_path / "digest.db") as store:
        provider = MockLLMProvider()
        first = run_digest(config, store, provider)
        assert first.status == "delivered"

        second = run_digest(config, store, provider)
        assert second.status == "empty_notified"
        assert second.article_count == 0


def test_run_digest_notifies_on_empty(tmp_path, fixtures_dir, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example.com/slack")

    sent_payloads = []

    class FakeResponse:
        def raise_for_status(self):
            return None

    def fake_post(url, json, timeout):
        sent_payloads.append(json)
        return FakeResponse()

    monkeypatch.setattr(httpx, "post", fake_post)

    config = _config_with_feed(fixtures_dir)
    config.feeds = []  # フィードなし = 常に0件

    with StateStore(tmp_path / "digest.db") as store:
        provider = MockLLMProvider()
        result = run_digest(config, store, provider)
        assert result.status == "empty_notified"
        assert len(sent_payloads) == 1
        assert "新着記事はありませんでした" in sent_payloads[0]["text"]


def test_run_digest_skips_notification_when_disabled(tmp_path, fixtures_dir, monkeypatch):
    config = _config_with_feed(fixtures_dir)
    config.feeds = []
    config.schedule.notify_on_empty = False

    called = []
    monkeypatch.setattr(httpx, "post", lambda *a, **k: called.append(1))

    with StateStore(tmp_path / "digest.db") as store:
        provider = MockLLMProvider()
        result = run_digest(config, store, provider)
        assert result.status == "empty_skipped"
        assert called == []


def test_run_digest_skips_mark_delivered_when_no_delivery_target(
    tmp_path, fixtures_dir, monkeypatch
):
    # 配信先の環境変数を未設定にする(=有効な配信先が1件も解決できない状態を再現)
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)

    called = []
    monkeypatch.setattr(httpx, "post", lambda *a, **k: called.append(1))

    config = _config_with_feed(fixtures_dir)
    with StateStore(tmp_path / "digest.db") as store:
        provider = MockLLMProvider()
        result = run_digest(config, store, provider)

        # Webhookには何も送信されていない
        assert called == []

        # 配信済み扱いにはならず、専用のステータスになっていること
        assert result.status == "no_delivery_target"
        assert result.error is not None

        # 記事はmark_deliveredされておらず、pendingのまま残っていること
        rows = store.get_seen_articles()
        assert len(rows) == 3
        assert all(row["delivered_at"] is None for row in rows)

        # 次回実行時にも同じ記事が再度新着候補になる(=持ち越しされる)こと
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example.com/slack")

        class FakeResponse:
            def raise_for_status(self):
                return None

        monkeypatch.setattr(httpx, "post", lambda url, json, timeout: FakeResponse())

        second = run_digest(config, store, provider)
        assert second.status == "delivered"
        assert second.article_count == 3


def test_run_digest_respects_max_articles_and_carries_over(tmp_path, fixtures_dir, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example.com/slack")

    class FakeResponse:
        def raise_for_status(self):
            return None

    monkeypatch.setattr(httpx, "post", lambda url, json, timeout: FakeResponse())

    config = _config_with_feed(fixtures_dir, digest=DigestConfig(max_articles=1, group_by="feed"))
    with StateStore(tmp_path / "digest.db") as store:
        provider = MockLLMProvider()
        result = run_digest(config, store, provider)
        assert result.status == "delivered"
        assert result.article_count == 1
        assert result.carried_over_count == 2

        # 配信対象外だった記事はpendingのまま(delivered_at未設定)であり、
        # 次回実行時に再度新着として扱われる(=持ち越し)
        rows = {row["url"]: row for row in store.get_seen_articles()}
        delivered_count = sum(1 for row in rows.values() if row["delivered_at"] is not None)
        pending_count = sum(1 for row in rows.values() if row["delivered_at"] is None)
        assert delivered_count == 1
        assert pending_count == 2


def test_run_digest_site_failure_isolation(tmp_path, fixtures_dir, monkeypatch):
    """1サイトの処理中に想定外の例外が発生しても、他サイトの処理・配信をブロックしないこと。"""
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example.com/slack")

    class FakeResponse:
        def raise_for_status(self):
            return None

    monkeypatch.setattr(httpx, "post", lambda url, json, timeout: FakeResponse())

    config = _config_with_two_feeds(fixtures_dir, "atom_publickey.xml", "Publickey")

    import src.core.runner as runner_module

    original_build_digest = runner_module.build_digest

    def flaky_build_digest(articles, digest_config):
        # サイトごとの呼び出し(単一フィードの記事のみ渡される)でのみ例外を送出する。
        # グローバルなbuild_digest呼び出し(複数フィード混在)は通常どおり動作させる。
        if articles and all(a.feed_name == "Publickey" for a in articles):
            raise RuntimeError("想定外のエラー(テスト用)")
        return original_build_digest(articles, digest_config)

    monkeypatch.setattr(runner_module, "build_digest", flaky_build_digest)

    with StateStore(tmp_path / "digest.db") as store:
        provider = MockLLMProvider()
        result = run_digest(config, store, provider)

        # 1サイトでも成功していれば全体は失敗にならない
        assert result.status == "delivered"

        site_statuses = {r.feed_name: r.status for r in result.site_results}
        assert site_statuses["Tech"] == "delivered"
        assert site_statuses["Publickey"] == "failed"

        rows = {row["url"]: row for row in store.get_seen_articles()}
        tech_rows = [r for r in rows.values() if r["feed_name"] == "Tech"]
        publickey_rows = [r for r in rows.values() if r["feed_name"] == "Publickey"]
        assert len(tech_rows) == 3
        assert len(publickey_rows) == 2
        # Techは配信成功しdelivered_atが確定している
        assert all(r["delivered_at"] is not None for r in tech_rows)
        # Publickeyは失敗しpendingのまま残っている(次回持ち越し)
        assert all(r["delivered_at"] is None for r in publickey_rows)


def test_run_digest_global_dedup_across_feeds(tmp_path, fixtures_dir, monkeypatch):
    """重複統合(URL基準)はサイト分割より前にグローバルで1回だけ行われること。"""
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example.com/slack")

    class FakeResponse:
        def raise_for_status(self):
            return None

    monkeypatch.setattr(httpx, "post", lambda url, json, timeout: FakeResponse())

    config = _config_with_two_feeds(fixtures_dir, "rss_duplicate.xml", "Dup")
    with StateStore(tmp_path / "digest.db") as store:
        provider = MockLLMProvider()
        result = run_digest(config, store, provider)

        assert result.status == "delivered"
        # Tech 3件 + Dup 2件 - 重複1件(aws-new-service) = 4件
        assert result.article_count == 4

        rows = {row["url"]: row for row in store.get_seen_articles()}
        assert len(rows) == 4
        assert all(r["delivered_at"] is not None for r in rows.values())

        # 重複はフィード定義順で先に出現した方(Tech側)に統合される
        dup_row = rows["https://example.com/tech/aws-new-service"]
        assert dup_row["feed_name"] == "Tech"
        assert dup_row["title"] == "AWSの新サービスが発表されました"


def test_run_digest_global_max_articles_cuts_by_feed_order(tmp_path, fixtures_dir, monkeypatch):
    """digest.max_articlesはサイト横断(グローバル)でサイト分割より前に適用され、
    フィード定義順でカットされること。"""
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example.com/slack")

    class FakeResponse:
        def raise_for_status(self):
            return None

    monkeypatch.setattr(httpx, "post", lambda url, json, timeout: FakeResponse())

    config = _config_with_two_feeds(
        fixtures_dir,
        "atom_publickey.xml",
        "Publickey",
        digest=DigestConfig(max_articles=3, group_by="feed"),
    )
    with StateStore(tmp_path / "digest.db") as store:
        provider = MockLLMProvider()
        result = run_digest(config, store, provider)

        assert result.status == "delivered"
        assert result.article_count == 3
        assert result.carried_over_count == 2

        # Tech(先に定義)の記事が優先的に選定され、Publickeyはまるごと持ち越しになる
        site_names = {r.feed_name for r in result.site_results}
        assert site_names == {"Tech"}

        rows = {row["url"]: row for row in store.get_seen_articles()}
        tech_rows = [r for r in rows.values() if r["feed_name"] == "Tech"]
        publickey_rows = [r for r in rows.values() if r["feed_name"] == "Publickey"]
        assert len(tech_rows) == 3
        assert all(r["delivered_at"] is not None for r in tech_rows)
        assert len(publickey_rows) == 2
        assert all(r["delivered_at"] is None for r in publickey_rows)


def test_run_digest_site_delivery_failure_keeps_failed_site_pending(
    tmp_path, fixtures_dir, monkeypatch
):
    """サイト単位で配信が失敗しても他サイトの状態確定をブロックせず、
    失敗サイトの記事はpendingのまま残り次回実行で再度新着候補になること。"""
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example.com/slack")

    class FakeResponse:
        def raise_for_status(self):
            return None

    fail_publickey = True

    def fake_post(url, json, timeout):
        # 送信されるテキストにサイト名の見出しが含まれることを利用し、
        # Publickeyサイトへの配信だけを(1回目のみ)失敗させる。
        if fail_publickey and "Publickey" in json["text"]:
            raise httpx.ConnectError("connection failed", request=httpx.Request("POST", url))
        return FakeResponse()

    monkeypatch.setattr(httpx, "post", fake_post)

    config = _config_with_two_feeds(fixtures_dir, "atom_publickey.xml", "Publickey")
    with StateStore(tmp_path / "digest.db") as store:
        provider = MockLLMProvider()
        result = run_digest(config, store, provider)

        assert result.status == "delivered"
        site_statuses = {r.feed_name: r.status for r in result.site_results}
        assert site_statuses["Tech"] == "delivered"
        assert site_statuses["Publickey"] == "failed"

        rows = {row["url"]: row for row in store.get_seen_articles()}
        tech_rows = [r for r in rows.values() if r["feed_name"] == "Tech"]
        publickey_rows = [r for r in rows.values() if r["feed_name"] == "Publickey"]
        assert all(r["delivered_at"] is not None for r in tech_rows)
        assert all(r["delivered_at"] is None for r in publickey_rows)

        # 次回実行時にPublickeyの記事が再度新着候補になり(=持ち越し)、
        # 配信が正常化すれば配信済みになること
        fail_publickey = False
        second = run_digest(config, store, provider)
        assert second.status == "delivered"
        assert second.article_count == 2
        second_site_names = {r.feed_name for r in second.site_results}
        assert second_site_names == {"Publickey"}

        rows_after = {row["url"]: row for row in store.get_seen_articles()}
        assert all(r["delivered_at"] is not None for r in rows_after.values())
