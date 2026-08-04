---
name: scraper
description: news-digestのscraper方式（RSS/Atomを提供しないサイト向け）のスクレイパーを生成・修正するスキル。RSS/Atomのない新しいサイトへの対応を依頼されたとき（生成モード）、または `uv run news-digest --db state/digest.db scrapers check` でスクレイパーの壊れ（status: error/empty）を検知し修正を依頼されたとき（修正モード）に起動する。
---

# news-digest スクレイパー生成・修正代行手順

あなた（AIコーディングエージェント）は、このドキュメントに従ってユーザーと対話しながら
news-digestの「scraper方式」（RSS/Atomフィードを提供していないサイト向けの取得方式）の
スクレイパースクリプトを**生成（author）**または**修正（repair）**してください。

このドキュメントは特定のAI製品・ベンダーに依存しないプレーンな指示書です。
どのAIコーディングエージェントで読み込んでも同じ手順で実行できるようにしてください。

## このSkillの位置づけ（作業を始める前に必ず理解しておくこと）

- スクレイパーは `scrapers/{scraper_id}/scraper.py` に配置され、
  `fetch(options: dict, http: httpx.Client) -> list[dict]` という契約のみを守る
  疎結合設計です。`src/core/models.py` の `Article` など、news-digest本体のモジュールを
  直接importしてはいけません。これは、あるサイトのレイアウト崩れやスクレイパーの
  バグによる影響をそのサイトの取得失敗に限定し、本体のデータモデルやパイプライン
  全体に波及させないための設計です。
- `scrapers/` 配下は `scrapers/example-blog/`（テンプレート）を除き `.gitignore` 対象です。
  スクレイパーは本リポジトリをローカルにインストールした各利用者が対象サイトに
  合わせて個別にカスタマイズするものであり、リポジトリ本体で共有・レビューする
  成果物ではありません。したがって **生成・修正した `scrapers/{id}/` はコミットせず、
  ブランチ作成やPR作成も行わないこと。** ローカルファイルとして生成・修正し、
  契約チェックリストで自己検証した内容をユーザーに直接提示してください。

このSkillには2つのモードがあります。ユーザーの依頼内容に応じてどちらのモードかを
判断し、以下の該当する手順に従ってください。

## 生成（author）モード

**トリガー**: ユーザーがRSS/Atomを提供していない新しいサイトの対応を依頼したとき。

### 手順

1. ユーザーから以下を確認する。
   - 対象サイトの一覧ページのURL
   - スクレイパーid（未指定であればサイト名やドメインから kebab-case で提案する。
     例: `example.com/blog` → `example-blog`）
2. 対象ページのHTML構造を取得・把握する。実際に一覧ページを取得し、記事タイトル・
   URL・日付・要約に相当する要素がどのタグ・クラス名・属性で表現されているかを
   特定する。
3. `scrapers/{id}/scraper.py` を作成する。
   - `fetch(options: dict, http) -> list[dict]` 契約を実装する。
   - 標準ライブラリ（`re` / `html.unescape` 等）のみで完結させることを推奨する。
   - 参考実装として `scrapers/example-blog/scraper.py` を必ず参照すること
     （`<article>` 要素の繰り返しから `url`/`title`/`summary_source`/`published_at`
     を正規表現で抽出するスタイル）。
   - news-digest本体のモジュール（`src.core.models` 等）をimportしないこと。
4. `scrapers/{id}/sample.html` を作成する。対象ページの実際の構造を模した
   オフラインfixtureとし、ネットワークなしでテストできるようにする。
5. `scrapers/{id}/expected.json` を作成する。`sample.html` に対して `fetch()` を
   実行した場合に返るべき期待値を手動で検証して記載する
   （`scrapers/example-blog/expected.json` の形式に倣う）。
6. 下記「契約チェックリスト」で自己検証する。
7. `config.yaml`（`config.example.yaml` ではなく実運用ファイル）の `feeds` に
   `source_type: scraper` + `scraper_id: {id}` のエントリを実際に追記する。
   カテゴリ等の値はユーザーに確認して埋める。
8. テスト送信を行う（下記「テスト送信」を参照）。
9. `scrapers/{id}/` は `.gitignore` 対象のローカルファイルであり、コミットや
   PR作成は行わない旨をユーザーに案内する。

## 修正（repair）モード

**トリガー**: `uv run news-digest --db state/digest.db scrapers check` の結果、
対象scraper_idの `status` が `error` または `empty` になっている（壊れ検知）とき、
人（ユーザー）がこのSkillを起動する。

### 手順

1. 対象の `scraper_id` を特定する。`scrapers check` の出力、または
   `source_health` テーブルの `error` 列のメッセージから原因の当たりをつける。
2. 既存の `scrapers/{id}/scraper.py` / `sample.html` / `expected.json` を読み、
   現在の実装が前提としているHTML構造を把握する。
3. 対象サイトの現在のHTML構造を再取得し、既存の `sample.html` と比較して
   何が変わったか（タグ構造・クラス名・属性など）を特定する。
4. `scrapers/{id}/scraper.py` のパース処理を新しい構造に合わせて修正する。
   `fetch(options, http) -> list[dict]` 契約・疎結合設計（本体モジュール非import）
   は維持すること。
5. `scrapers/{id}/sample.html` を新しい構造のfixtureに更新し、`expected.json` も
   新しい期待値に更新する。
6. 下記「契約チェックリスト」で自己検証する。
7. テスト送信を行う（下記「テスト送信」を参照）。
8. `scrapers/{id}/` は `.gitignore` 対象のローカルファイルであり、コミットや
   PR作成は行わない旨をユーザーに案内する。

## テスト送信（両モード共通）

`sample.html` に対する `fetch()` の自己検証はオフラインの契約確認に過ぎず、
対象サイトへの実際のアクセス・要約・配信までは検証していない。生成・修正の
最後に、実際のパイプラインを1回走らせて疎通を確認すること。

1. **実行前に必ずユーザーに確認する。** `uv run news-digest --db state/digest.db run`
   は `config.yaml` の `delivery` に設定された実際の配信先（Slack/Google Chat等の
   webhook）に本番配信される。テスト目的でも実際のチャンネルに通知が届くことを
   ユーザーに伝え、実行してよいか確認してから進める。
2. 承認を得たら `uv run news-digest --db state/digest.db run` を実行する
   （このコマンドはconfig.yamlの全フィードを対象に1回分のバッチを実行する。
   対象スクレイパーのみを分離実行する手段は現状ないため、他フィードの新着も
   同時に配信される点をユーザーに伝えておく）。
3. `uv run news-digest --db state/digest.db scrapers check` で対象 `scraper_id` の
   `status` が `ok` であることを確認する。`error`/`empty` の場合は原因を調査し、
   必要であれば修正（repair）モードの手順に戻る。
4. 配信先に実際に通知が届いたか（記事が縮退配信ではなく要約付きで届いているか
   等）をユーザーに確認してもらう。

## 契約チェックリスト（両モード共通）

生成・修正のたびに、以下を必ず自己チェックしてください。

- [ ] `fetch(options: dict, http) -> list[dict]` のシグネチャ通りか
- [ ] `src/core/models.py` 等news-digest本体のモジュールをimportしていないか
- [ ] 戻り値の各要素は `url` と `title` が非空か（欠落・空文字は契約違反として
      取得失敗扱いになる）
- [ ] `sample.html` に対して実際に `fetch()` 相当の処理を動かし、`expected.json`
      と一致することを手動で確認したか（可能であれば `tests/test_scraper_fetcher.py`
      のテストパターンを参考に、簡単なPythonスクリプトで検証することを推奨する）
- [ ] `config.yaml`（実運用ファイル）にfeedエントリを実際に追記したか
- [ ] 実配信先へ本番配信されることをユーザーに確認したうえでテスト送信を行い、
      `scrapers check` の `status` が `ok` であることを確認したか
- [ ] `scrapers/{id}/` はコミット・PR作成をせず、ローカルファイルとしてユーザーに
      直接提示したか
