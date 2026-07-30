"""Claude Code CLIサブプロセスを利用した要約プロバイダー。

このプロバイダーのみ、1日分の記事をまとめてサブプロセス1回で要約する
summarize_batch を独自実装する。API課金ではなくCLIのサブスクリプション
認証（ログインセッション）を利用する想定のため、子プロセスには
ANTHROPIC_API_KEY 等の機微な環境変数を一切引き継がない。
"""

from __future__ import annotations

import json
import os
import re
import subprocess

from src.config import LLMConfig
from src.core.models import Article
from src.llm.base import LLMProvider, SummaryResult, coerce_score


class ClaudeCodeCliResponseError(ValueError):
    """CLI応答のJSONパースに失敗した場合に送出する。"""


def _minimal_subprocess_env() -> dict[str, str]:
    """子プロセスに引き継ぐ環境変数を必要最小限に絞り込む。

    ANTHROPIC_API_KEY 等の機微な値は明示的に含めない。
    CLIサブスクリプション認証はユーザーのログインセッション
    （OSキーチェーン等）に紐づくため、APIキーを渡す必要はない。
    """
    allowed_keys = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "USER")
    return {k: os.environ[k] for k in allowed_keys if k in os.environ}


def _extract_json_object(text: str) -> str:
    """テキストからJSONオブジェクト部分を抽出する。

    モデル出力がmarkdownのコードフェンス（```json ... ```）で囲まれている
    場合や前後に説明文が付与されている場合を考慮し、最初の '{' から
    対応する最後の '}' までを抜き出す。
    """
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        return fence_match.group(1)

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ClaudeCodeCliResponseError("応答テキストにJSONオブジェクトが見つかりません")
    return text[start : end + 1]


class ClaudeCodeCliProvider(LLMProvider):
    def __init__(self, config: LLMConfig, request_importance_score: bool = False):
        cli_config = config.claude_code_cli
        self._command = cli_config.command
        self._model = cli_config.model
        self._timeout_seconds = cli_config.timeout_seconds
        self._max_retries = cli_config.max_retries
        self._max_input_chars = config.max_input_chars
        self._language = config.summary_language
        self._style = config.summary_style
        self._request_importance_score = request_importance_score

    # --- LLMProvider interface -------------------------------------------------

    def summarize(self, article: Article) -> SummaryResult:
        results = self.summarize_batch([article])
        url = article.normalized_url()
        if url not in results:
            raise RuntimeError(f"記事の要約に失敗しました: {url}")
        return results[url]

    def summarize_batch(self, articles: list[Article]) -> dict[str, SummaryResult]:
        """1日分の記事をまとめてサブプロセス1回で要約する。

        タイムアウト・失敗時は max_retries 回まで再試行する。
        最終的に失敗した場合は例外を送出し、呼び出し元（runner）が
        縮退配信にフォールバックできるようにする。
        """
        if not articles:
            return {}

        prompt = self._build_prompt(articles)

        last_error: Exception | None = None
        for _attempt in range(self._max_retries + 1):
            try:
                stdout = self._run_cli(prompt)
                return self._parse_response(stdout)
            except (subprocess.TimeoutExpired, ClaudeCodeCliResponseError, RuntimeError) as exc:
                last_error = exc
                continue

        raise RuntimeError(
            f"claude-code-cli による要約が {self._max_retries + 1} 回試行しても"
            f"失敗しました: {last_error}"
        ) from last_error

    # --- internal ----------------------------------------------------------------

    def _build_prompt(self, articles: list[Article]) -> str:
        payload = [
            {
                "url": article.normalized_url(),
                "title": article.title,
                "excerpt": article.summary_source[: self._max_input_chars],
            }
            for article in articles
        ]
        articles_json = json.dumps(payload, ensure_ascii=False)
        if self._request_importance_score:
            return (
                "あなたはニュース要約アシスタントです。"
                f"以下のJSON配列で渡す各ニュース記事を{self._language}で要約し、"
                f"あわせて重要度を0〜100の数値で評価してください。スタイル: {self._style}\n"
                "出力は、各記事のurlをキー、"
                '{"summary": "要約文字列", "score": <0-100の数値>} を値にした'
                "JSONオブジェクトのみを返してください。説明文やコードフェンスは含めないでください。\n\n"
                f"記事一覧: {articles_json}"
            )
        return (
            "あなたはニュース要約アシスタントです。"
            f"以下のJSON配列で渡す各ニュース記事を{self._language}で要約してください。"
            f"スタイル: {self._style}\n"
            "出力は、各記事のurlをキー、要約文字列を値にしたJSONオブジェクトのみを"
            "返してください。説明文やコードフェンスは含めないでください。\n\n"
            f"記事一覧: {articles_json}"
        )

    def _run_cli(self, prompt: str) -> str:
        cmd = [self._command, "-p", prompt, "--output-format", "json", "--tools", ""]
        if self._model:
            cmd += ["--model", self._model]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
                env=_minimal_subprocess_env(),
                check=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"claude CLIコマンド '{self._command}' が見つかりません。"
                "PATHの設定を確認してください。"
            ) from exc

        if result.returncode != 0:
            raise RuntimeError(
                f"claude CLIが異常終了しました (code={result.returncode}): {result.stderr}"
            )
        return result.stdout

    def _parse_response(self, stdout: str) -> dict[str, SummaryResult]:
        """2段階JSONパース。

        1段階目: CLI標準出力全体をトップレベルJSONとしてパースする
        （print modeのJSON出力形式、例: {"result": "...model output text..."}）。
        2段階目: 1段階目で得られたテキストから、期待する {url: ...} 形式の
        JSONを抽出・パースする。

        {url: ...} の各値は以下のいずれかを後方互換で受け付ける:
        - 新形式: {"summary": "...", "score": <0-100>} という辞書
        - 旧形式: 要約文字列そのもの
        いずれの場合も score が欠落・パース不能なら importance_score=None にフォールバックする
        （JSON自体が壊れている等、応答全体のパース失敗は従来通り例外を送出する）。
        """
        stripped = stdout.strip()
        try:
            top_level = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ClaudeCodeCliResponseError(
                f"CLI標準出力をJSONとしてパースできませんでした: {exc}"
            ) from exc

        if isinstance(top_level, dict) and isinstance(top_level.get("result"), str):
            text = top_level["result"]
        elif isinstance(top_level, str):
            text = top_level
        elif isinstance(top_level, dict):
            # すでに {url: ...} 形式で返ってきた場合はそのまま使う。
            return {str(k): self._coerce_entry(v) for k, v in top_level.items()}
        else:
            raise ClaudeCodeCliResponseError("予期しないトップレベルJSON構造です")

        json_text = _extract_json_object(text)
        try:
            entries = json.loads(json_text)
        except json.JSONDecodeError as exc:
            raise ClaudeCodeCliResponseError(
                f"応答テキストから抽出したJSONのパースに失敗しました: {exc}"
            ) from exc

        if not isinstance(entries, dict):
            raise ClaudeCodeCliResponseError("要約結果がJSONオブジェクトではありません")

        return {str(k): self._coerce_entry(v) for k, v in entries.items()}

    @staticmethod
    def _coerce_entry(value: object) -> SummaryResult:
        """{url: ...} の1エントリを SummaryResult に変換する後方互換ヘルパー。

        新形式（{"summary": ..., "score": ...} 辞書）・旧形式（文字列）の
        両方を受け付ける。score欠落・数値変換不能時はimportance_score=Noneにする。
        """
        if isinstance(value, dict):
            summary_value = value.get("summary")
            summary = (
                summary_value
                if isinstance(summary_value, str) and summary_value
                else json.dumps(value, ensure_ascii=False)
            )
            score = coerce_score(value.get("score"))
            return SummaryResult(summary=summary, importance_score=score)
        return SummaryResult(summary=str(value), importance_score=None)
