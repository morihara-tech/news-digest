# news-digest

複数のRSS/Atomフィードを収集し、キーワードフィルタとLLM要約を適用した上で、
1日1回Slack / Google Chatへダイジェスト配信するパーソナルニュースダイジェストです。

MCPサーバー（`src/server.py`）とCLIバッチ（`src/cli.py`）の両方から同じコアロジック
（`src/core/`）を呼び出す構成になっており、cron等の定期実行と、Claude Code等の
MCPクライアントからの手動操作の両方に対応します。

## セットアップ

### AIエージェントによるセットアップ代行（推奨）

AIコーディングエージェント（Claude Code、Cursor、Windsurf等どれでも構いません）を
使える場合は、`.agent/skills/setup.md` の内容をエージェントに渡し、対話形式での
セットアップ代行を依頼することもできます。エージェントがLLMプロバイダー・配信先・
購読フィード等をヒアリングした上で、`.env`・`config.yaml`の生成から`uv sync`・
妥当性検証・試験実行までを代行します。既存の`.env`/`config.yaml`がある場合は
上書き前に必ず確認が入ります。

`.agent/skills/setup.md` は特定のAI製品・ベンダーに依存しないプレーンなMarkdown
文書のため、上記以外のAIコーディングエージェントでも同様に利用できます。

以下は、AIエージェントを使わず手動でセットアップする場合の手順です（代替手段として
利用できます）。

### 1. 依存関係のインストール

[uv](https://docs.astral.sh/uv/) を利用します。

```bash
uv sync
```

### 2. 環境変数の設定

```bash
cp .env.example .env
```

`.env` を編集し、使用するプロバイダー・配信先に応じて値を設定してください。

| 変数名 | 用途 |
|---|---|
| `ANTHROPIC_API_KEY` | `llm.provider: claude` を使う場合のAnthropic APIキー。`claude-code-cli` を使う場合は空欄のままでよい |
| `SLACK_WEBHOOK_URL` | Slack Incoming Webhook URL |
| `GOOGLE_CHAT_WEBHOOK_URL` | Google Chat Incoming Webhook URL |

`.env` はGit管理対象外です（`.gitignore` 参照）。実際のAPIキー・Webhook URLを
コミットしないよう注意してください。

### 3. 設定ファイルの作成

```bash
cp config.example.yaml config.yaml
```

`config.yaml` を編集し、使用するLLMプロバイダー・配信先・購読フィードを設定してください。
`config.yaml` もGit管理対象外です。

### 4. 動作確認

```bash
uv run news-digest --config config.yaml --db state/digest.db run
```

## 主要な設定項目（config.yaml）

| キー | 説明 |
|---|---|
| `llm.provider` | `claude` / `local-ai` / `claude-code-cli` のいずれか。切替はこの値の変更のみで完結する |
| `llm.model` | プロバイダー依存のモデルID |
| `llm.api_key_env` | `claude` プロバイダーで使うAPIキーの環境変数名 |
| `llm.base_url` | `local-ai`（Ollama等OpenAI互換API）のベースURL |
| `llm.claude_code_cli.command` | Claude Code CLIの実行コマンド名（既定 `claude`） |
| `llm.claude_code_cli.timeout_seconds` | CLIサブプロセスのタイムアウト秒数 |
| `llm.claude_code_cli.max_retries` | CLIサブプロセス失敗時の再試行回数 |
| `llm.max_input_chars` | 要約前に本文を切り詰める文字数上限（コスト制御） |
| `llm.max_articles_to_summarize` | 1日あたりの要約対象記事数の上限（コスト上限）。超過分は要約せず「タイトル+リンクのみ」の縮退配信になる |
| `delivery[].format` | `slack` / `google_chat` |
| `delivery[].webhook_url_env` | Webhook URLを格納した環境変数名 |
| `schedule.notify_on_empty` | 新着0件の日にも「本日は新着なし」を通知するか |
| `digest.max_articles` | 1回の配信件数上限（下記「配信件数上限の挙動」を参照） |
| `digest.group_by` | 各サイト（フィード）のメッセージ内でのグルーピング単位（`feed` / `category` / `none`）。下記「サイト（フィード）ごとの独立配信」も参照。`group_by="feed"` の場合、メッセージ内グループ見出しとサイト見出しが実質的に同じ文字列になる |
| `retention.seen_ttl_days` | 既読（配信済み）とみなすTTL日数。既定90日 |
| `filters.include_keywords` / `filters.exclude_keywords` | グローバルフィルタ。フィード単位の `filters` が指定されていればそちらが優先（上書き）される |
| `feeds[].filters` | フィード単位のキーワードフィルタ。指定時はグローバルフィルタより優先 |
| `feeds[].source_type` | `rss`（既定、feedparserによるRSS/Atom取得） / `scraper`（RSS/Atomがないサイト向けのスクレイパー方式） |
| `feeds[].scraper_id` | `source_type: scraper` の場合に必須。`scrapers/{scraper_id}/scraper.py` を参照する |

### サイト（フィード）ごとの独立配信

RSS取得〜要約〜配信は、サイト（フィード）ごとに独立した処理として実行されます。
具体的には、フィード横断の重複統合・既配信除外・配信件数上限（後述）を
グローバルに1回適用したうえで、選定された記事群をフィード名で分割し、
フィードごとに要約とWebhook配信を行います。各フィードは独立したチャット
メッセージとして配信されるため、複数サイトの記事が1つのメッセージに
まとまることはありません。

この分割により、1サイトのRSS取得・要約・配信の失敗が他サイトの処理を
ブロックしません（障害分離）。あるサイトの処理が失敗しても、他のサイトは
通常どおり要約・配信され、失敗したサイトの記事のみがpendingのまま残り
次回バッチで再度候補になります。

### 配信件数上限の挙動

`digest.max_articles` はサイト横断（グローバル）の上限であり、記事群を
フィードごとに分割するより前に適用されます。上限超過分の記事は「削除」では
なく「その回の配信対象から除外」されるだけであり、sqlite3の状態DB上で
`delivered_at` が未確定のまま残るため、次回以降のバッチ実行で改めて配信候補
として扱われます（=自動的に持ち越されます）。フィード側で記事が削除される、
または90日TTLを超過するまで、この持ち越しは継続します。

上限適用はフィードの定義順（`config.yaml` の `feeds` 配列の並び順）で行われる
ため、後方に定義されたフィードほど上限に達しやすく持ち越されやすくなります。

### 要約失敗・コスト超過時の縮退配信

- LLMによる要約が例外・タイムアウトで失敗した記事は、記事自体を捨てずに
  「タイトル + リンクのみ」の縮退フォーマットで配信します。この要約失敗による
  degraded判定は**サイトごとに独立して**行われ、あるサイトの要約失敗が他サイトの
  要約結果に影響しません。
- `llm.max_articles_to_summarize` を超えた記事も同様に縮退配信されます。
  ただしこちらのコスト上限判定は、サイト分割より前にサイト横断で**グローバルに
  1回だけ**行われる点が要約失敗判定と異なります。

### RSS/Atomがないサイトへの対応（scraper方式）

RSS/Atomフィードを提供していないサイトは、`config.yaml` の該当フィードで
`source_type: scraper` と `scraper_id` を指定することで、専用のスクレイパー
スクリプト経由で記事を取得できます。

```yaml
feeds:
  - name: "Example Blog"
    url: "https://example.com/blog"
    category: tech
    source_type: scraper
    scraper_id: example-blog
```

スクレイパーの契約は以下の通りです。

- `scrapers/{scraper_id}/scraper.py` に `fetch(options: dict, http: httpx.Client) -> list[dict]`
  を実装すること。
- `options` は `{"url": フィードのurl, "feed_name": フィード名, "category": カテゴリ}`。
- 戻り値の各dictは `url` / `title` が必須（欠落・空の場合は契約違反として取得失敗扱いになる）。
  `summary_source` / `published_at` / `category` は任意。
- スクレイパーは `src/core/models.py` の `Article` など、news-digest本体のモジュールを
  直接importしないこと。スクレイパーは疎結合な `list[dict]` の返却のみに責任を持ち、
  本体側（`src/core/scraper_fetcher.py`）が `Article` への変換を担う設計になっています。
  これにより、あるサイトのレイアウト崩れ・スクレイパーのバグによる影響がそのサイトの
  取得失敗に限定され、本体のデータモデルやパイプライン全体に波及しません。
- サンプル実装として `scrapers/example-blog/` を参照してください。`sample.html`
  （取得対象ページを模したオフラインfixture）と `expected.json`（`fetch()` が返すべき
  期待値）を併せてコミットし、`tests/test_scraper_fetcher.py` のようにテストで
  動作を検証することを推奨します。

スクレイパーの取得結果（0件取得・例外・スキーマ不一致などの壊れ検知）は
sqlite3の `source_health` テーブルに自動記録されます。以下のコマンドで
最新の状態を確認できます。

```bash
uv run news-digest --db state/digest.db scrapers check
```

いずれかのスクレイパーが `ok` 以外の状態であれば終了コード1を返すため、
cron等の監視に組み込むこともできます。

なお、壊れたスクレイパーの**修正**はClaude Skillを人が起動して行う
Human-in-the-loopの運用を想定しており、本リポジトリの範囲では自動修正は
行いません（Skill定義自体は別Issueで対応予定です）。

### 重複統合・既読管理・冪等性

- 記事のユニークキーはURL文字列です。
- 重複統合（URL基準）は、記事群をフィードごとに分割するより前に、サイト横断で
  グローバルに1回だけ行われます。同一URLが複数フィードに含まれる場合、
  `config.yaml` の `feeds` 配列で先に定義されたフィード側の記事に統合されます。
- sqlite3 (`state/digest.db`) の `seen_articles` テーブルで既読状態を管理します。
  `delivered_at` は**サイトごとの配信成功後にのみ**確定します。配信前は
  `first_seen_at` のみが記録された pending 状態であり、その状態のまま次回実行を
  迎えた記事は再度新着候補として扱われます。これにより、Webhook配信が失敗した
  場合の再実行で二重配信を避けつつ、未配信記事を確実に再送できます。
- 1サイトの配信失敗は他サイトの状態確定をブロックしません。失敗したサイトの
  記事は `delivered_at` が未確定のままpendingで残り、次回実行で再度新着候補と
  なります（成功した他サイトの記事は通常どおり `delivered_at` が確定します）。
- `retention.seen_ttl_days`（既定90日）以内に配信済みの同一URLは重複配信しません。

## cron実行時の注意（PATH・環境変数）

cronジョブは非対話シェルで実行され、ログインシェルの `PATH` や環境変数を
引き継ぎません。`uv` コマンドがcrontab内で見つからない、`.env` の値が
読み込まれない、といった問題を避けるため、以下のいずれかの対応が必要です。

- crontab内で `uv` や `claude` コマンドの絶対パス（`which uv` / `which claude` で確認）
  を指定する
- crontab内で必要な環境変数（`PATH` など）を明示的に設定する

### crontab例

```cron
# 毎朝8時に実行する例
0 8 * * * cd /path/to/news-digest && /home/user/.local/bin/uv run news-digest run >> state/cron.log 2>&1
```

## cron vs systemd user timer / launchd user agent

- **cron**: 非対話・環境変数が最小限しか引き継がれません。`ANTHROPIC_API_KEY` の
  ような値はcrontab内で明示的に設定するか、`.env` ファイル経由で読み込む設計に
  する必要があります。`llm.provider: claude` や `local-ai` のようにAPIキー/HTTPで
  完結するプロバイダーであればcronで問題なく動作します。
- **`claude-code-cli` プロバイダーを使う場合の注意**: Claude Code CLIの認証が
  OSキーチェーンやログインセッションに紐づくサブスクリプション認証の場合、
  cronのような非対話バッチジョブからはその認証情報に到達できないことがあります。
  この場合は、ユーザーセッション内で動作する **systemd user timer**（Linux）や
  **launchd user agent**（macOS）の利用を推奨します。これらはログインセッションの
  文脈で実行されるため、CLIの認証情報への到達性が確保されやすくなります。

### systemd user timer の例（Linux）

`~/.config/systemd/user/news-digest.service`:

```ini
[Unit]
Description=News Digest daily batch

[Service]
Type=oneshot
WorkingDirectory=%h/path/to/news-digest
ExecStart=%h/.local/bin/uv run news-digest run
```

`~/.config/systemd/user/news-digest.timer`:

```ini
[Unit]
Description=Run News Digest daily at 08:00

[Timer]
OnCalendar=*-*-* 08:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

有効化:

```bash
systemctl --user enable --now news-digest.timer
```

### launchd user agent の例（macOS）

`~/Library/LaunchAgents/tech.morihara.news-digest.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>tech.morihara.news-digest</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/USERNAME/.local/bin/uv</string>
    <string>run</string>
    <string>news-digest</string>
    <string>run</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/Users/USERNAME/path/to/news-digest</string>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>8</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>
</dict>
</plist>
```

読み込み:

```bash
launchctl load ~/Library/LaunchAgents/tech.morihara.news-digest.plist
```

## MCPサーバーの起動方法

```bash
uv run python -m src.server
```

Claude Code等のMCPクライアントから接続する場合、プロジェクトルートに
`.mcp.json` を作成し、以下のように登録します（`.mcp.json` はローカル専用設定
として `.gitignore` されているため、各自の環境で作成してください）。

```json
{
  "mcpServers": {
    "news-digest": {
      "command": "uv",
      "args": ["run", "python", "-m", "src.server"],
      "cwd": "/path/to/news-digest"
    }
  }
}
```

提供するツール:

| ツール | 用途 |
|---|---|
| `get_config` | 現在の設定概要を参照する（Webhook URL等の機微情報は含まない） |
| `list_registered_feeds` | 登録フィード一覧とフィルタ設定を参照する |
| `get_run_history` | 配信バッチの実行履歴を参照する |
| `get_recent_articles` | 直近に検知した記事の既読/配信状態を参照する |
| `run_digest_now` | 配信バッチを即時1回実行する（手動実行） |
| `submit_feedback` | 記事に対するフィードバックを記録する |

## テスト

```bash
uv run pytest
```

すべてのテストは外部ネットワーク・外部LLM課金に依存しません。フィード取得は
`tests/fixtures/` 配下のローカル固定RSS/Atom XMLを使用し、LLM要約は
`tests/mock_llm_provider.py` のモック実装、または `subprocess.run` をモックした
`claude-code-cli` プロバイダーのユニットテストで代替しています。

## ディレクトリ構成

```
src/
  server.py     MCPサーバーのエントリポイント
  cli.py        CLIエントリポイント（cronバッチ実行等）
  config.py     pydanticベースの設定モデル・ロード処理
  core/         サーバーとCLIが共有するコアロジック
    feed_fetcher.py    feedparserベースのフィード取得・フィルタ適用（scraper方式へのディスパッチも担う）
    scraper_fetcher.py RSS/Atomがないサイト向けのスクレイパー経由の記事取得
    dedup.py           URL基準の重複統合
    state.py           sqlite3状態管理（source_healthを含む）
    digest.py          要約・ダイジェスト組み立て
    delivery.py        Slack/Google Chat配信
    runner.py          配信バッチのオーケストレーション
  llm/          LLMProvider抽象化と各プロバイダー実装
  tools/        MCPツール実装（設定管理・履歴参照・手動実行・フィードバック記録）
scrapers/       source_type: scraper のフィード用スクレイパースクリプト（サイトごとに1ディレクトリ）
  example-blog/ サンプルスクレイパー（sample.html/expected.jsonを併せて配置）
tests/
  fixtures/     ローカル固定RSS/Atom XML
  test_*.py
```

## License

MIT License. See [LICENSE](LICENSE) for details.
