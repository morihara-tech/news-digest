# CLAUDE.md

news-digest リポジトリでの作業に必要な、コードベース固有のアーキテクチャと規約をまとめる。

## アーキテクチャ概要

RSS/Atomフィード → フィルタ → 要約 → Webhook配信のパイプライン。MCPサーバー（`src/server.py`）とCLIバッチ（`src/cli.py`）の両方が `src/core/` 配下の共有ロジックを呼び出す設計になっており、実行経路によってロジックが分岐しない。

### パイプラインの流れ

`src/core/runner.py` の `run_digest()` が全体のオーケストレーションを担う。

1. **取得**: `src/core/feed_fetcher.py` の `fetch_all()` で各フィードを feedparser でパースし、フィード単位/グローバルのフィルタを適用する。
2. **重複統合**: `src/core/dedup.py` の `filter_new_articles()` でURLを基準に重複除去し、TTL（`config.retention.seen_ttl_days`）で既読を除外する。
3. **要約**: `src/core/digest.py` の `summarize_articles()` がLLM要約を行う。失敗時は個別記事に `article.degraded = True` を設定する。
4. **件数上限**: `src/core/digest.py` の `build_digest()` で `config.digest.max_articles` を適用する。上限超過分は記事を削除せず、`delivered_at` が確定しないため次回以降のバッチで自然に再度候補となる（持ち越し）。
5. **配信**: `src/core/delivery.py` の `deliver_digest()` がWebhookへ送信する。一部配信先が失敗しても他の配信先への送信は継続する。
6. **状態確定**: `src/core/state.py`（`StateStore`）で、配信が成功した記事についてのみ `delivered_at` を設定する（冪等性の確保）。

### LLMプロバイダー抽象化

- `src/llm/base.py` の `LLMProvider`（ABC）が `summarize()` / `summarize_batch()` のインターフェースを統一する。`summarize_batch()` のデフォルト実装は1記事ずつ `summarize()` を呼び、個別記事の失敗は握りつぶして結果dictから除外する（呼び出し元の縮退配信に委ねる）。
- `src/llm/factory.py` の `create_llm_provider()` が `config.llm.provider`（`claude` / `local-ai` / `claude-code-cli`）に応じて対応するプロバイダー実装を動的にロードする。

### 設定管理（`src/config.py`）

- Pydanticモデル（`AppConfig` ほか）で `config.yaml` をロード時にバリデーションする。
- `config.example.yaml` をテンプレートとし、実運用の `config.yaml` は `.gitignore` 対象で手動作成する前提。
- `FeedConfig.effective_filters()` により、フィード単位のフィルタ設定がグローバルフィルタより優先される。
- 機微情報（APIキー、Webhook URL）は環境変数（`.env`）で管理し、`get_env()`（`os.environ.get()` の薄いラッパー）経由で取得する。テスト時にモック差し替えしやすくするための設計。

## コーディング規約・実装方針

### エラーハンドリング方針（一貫パターン: 例外を投げず部分失敗を握りつぶし縮退配信）

1. **フィード取得失敗**（`src/core/feed_fetcher.py` `fetch_feed_entries()`）: `feedparser` の結果が `bozo` かつエントリ0件の場合は `logger.warning()` を出力し空リストを返す（例外は送出しない）。
2. **要約失敗**（`src/llm/base.py` `summarize_batch()`、`src/core/digest.py` `summarize_articles()`）: 個別記事の例外は握りつぶし `article.degraded = True` / `degraded_reason` を設定する。配信ロジック側（`src/core/delivery.py` の `_format_article_line()` 等）が「タイトル＋リンクのみ」の縮退フォーマットで配信する。要約対象数の上限（`config.llm.max_articles_to_summarize`）超過分も同様に縮退扱いになる。
3. **配信失敗**（`src/core/delivery.py` `deliver_digest()` / `send_webhook()`）: `httpx.HTTPError` を `DeliveryError` でラップする。1配信先の失敗は他配信先への送信を妨げない。全配信先が失敗した場合のみ `DeliveryError` を送出する。
4. **全体エラー**（`src/core/runner.py` `run_digest()`）: 最外側の `try/except` で予期しない例外を握りつぶし、`RunResult(status="failed", ...)` として結果に記録する（バッチ全体を落とさない）。

### モジュール間の責任分離

- `src/core/runner.py`: 全体フロー制御・エラー処理・実行結果（`RunResult`）の記録。
- `src/core/{feed_fetcher,dedup,digest,delivery}.py`: パイプラインの各ステージ。単機能でテスト可能な単位に分割されている。
- `src/llm/`: LLM呼び出し（プロバイダー間で `LLMProvider` インターフェースにより互換性を持たせる）。
- `src/config.py`: Pydanticによるstrictバリデーション（不正・欠損設定を起動時に早期検出する）。

### 設定・環境変数の原則

- 機微情報（APIキー、Webhook URL）は `.env`、ロジック・振る舞いは `config.yaml` で管理する。
- 環境変数が未設定でも例外にはせず、警告ログを出してその配信先/機能をスキップする（例: `src/core/delivery.py` `resolve_delivery_targets()`）。

### テストの書き方

- ネットワークに依存しない: `tests/fixtures/` の固定RSS/Atom XMLと monkeypatch（`httpx.post` や環境変数の差し替え）を使う。
- LLM呼び出しは `tests/mock_llm_provider.py` のモック実装を使う。
- 各モジュールを関数単位でテストしつつ、`tests/test_runner.py` のような統合テストで冪等性（特に `delivered_at` が確定するタイミング）を検証する。
- `tmp_path` フィクスチャで一時DBを、`tests/conftest.py` の `fixtures_dir` フィクスチャで固定XMLファイルの配置先を参照する。
