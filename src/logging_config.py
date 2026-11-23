"""CLI / MCPサーバー共通のロギング設定と、秘密情報のマスク処理。

Google Chat Webhook URLはクエリ文字列に `key` / `token` を含み、Slack Webhook URLは
パス自体が秘密情報である。httpx のINFOログや例外メッセージ（`for url '...'`）に
これらが平文で出力されるのを防ぐため、ハンドラにマスク用Filterを付与する。

方針（多層防御）:
1. ハンドラ（ルートロガーのハンドラ）にFilterを付与する。ロガーではなくハンドラに付けることで、
   httpx/anthropic等の子ロガーから伝播したレコードにも効く。
2. httpx / httpcore ロガーをWARNING以上にし、そもそもリクエストURL行を出さない。
3. 環境変数から解決した実際のWebhook URL値は `register_secret()` で完全一致マスクの対象にする。
"""

from __future__ import annotations

import logging
import re

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
MASK = "***"

# Webhook配信先ホスト。ホスト名までは残し、パス・クエリを丸ごと伏せる。
# URLエンコードされた形（https%3A%2F%2Fchat.googleapis.com%2F...）にも対応する。
_WEBHOOK_URL_RE = re.compile(
    r"(?P<scheme>https?(?:://|%3A%2F%2F))"
    r"(?P<host>chat\.googleapis\.com|hooks\.slack\.com)"
    r"(?:/|%2[Ff])[^\s'\"<>]*",
    re.IGNORECASE,
)

# 任意のURLに付くクエリ中の機微パラメータ（`?key=...` / `&token=...` / エンコード形）。
_SENSITIVE_QUERY_RE = re.compile(
    r"(?P<prefix>(?:[?&]|%3[Ff]|%26)"
    r"(?:key|token|api[_-]?key|access[_-]?token|auth|secret|signature|sig|password)"
    r"(?:=|%3[Dd]))[^&\s'\"<>]*",
    re.IGNORECASE,
)

# Authorization / x-api-key ヘッダ値、Anthropic APIキー形式。
_BEARER_RE = re.compile(r"(?i)\b(?P<prefix>bearer\s+)[A-Za-z0-9._~+/=-]+")
_HEADER_RE = re.compile(
    r"(?i)(?P<prefix>['\"]?(?:authorization|x-api-key)['\"]?\s*[:=]\s*['\"]?)[^\s'\",}]+"
)
_ANTHROPIC_KEY_RE = re.compile(r"sk-ant-[A-Za-z0-9_-]+")

# 環境変数から解決した実際の秘密値（完全一致マスク用）。
_registered_secrets: set[str] = set()


def register_secret(value: str | None) -> None:
    """完全一致でマスクしたい値（例: 環境変数から解決したWebhook URL）を登録する。"""
    if value and len(value) >= 8:
        _registered_secrets.add(value)


def mask_secrets(text: str) -> str:
    """文字列中の秘密情報をマスクして返す。"""
    text = _WEBHOOK_URL_RE.sub(lambda m: f"{m.group('scheme')}{m.group('host')}/{MASK}", text)
    text = _SENSITIVE_QUERY_RE.sub(lambda m: f"{m.group('prefix')}{MASK}", text)
    text = _BEARER_RE.sub(lambda m: f"{m.group('prefix')}{MASK}", text)
    text = _HEADER_RE.sub(lambda m: f"{m.group('prefix')}{MASK}", text)
    text = _ANTHROPIC_KEY_RE.sub(f"sk-ant-{MASK}", text)
    # 上記パターンで拾えない形の登録済み秘密値を完全一致で最後に伏せる（長い値を先に置換）。
    # パターン側を先に適用するのは、ホスト名など追跡用情報を残すため。
    for secret in sorted(_registered_secrets, key=len, reverse=True):
        text = text.replace(secret, MASK)
    return text


class SecretMaskingFilter(logging.Filter):
    """ログレコードのメッセージ・例外情報・スタック情報から秘密情報をマスクするFilter。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = mask_secrets(record.getMessage())
        record.args = ()
        if record.exc_info:
            # 整形済みtracebackをマスクして exc_text に固定し、元の例外オブジェクトは参照させない
            exc_text = logging.Formatter().formatException(record.exc_info)
            record.exc_text = mask_secrets(exc_text)
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = mask_secrets(record.exc_text)
        if record.stack_info:
            record.stack_info = mask_secrets(record.stack_info)
        return True


def setup_logging(level: int = logging.INFO) -> None:
    """共通ロギング設定。冪等（複数回呼んでもハンドラ・Filterは重複しない）。

    ログは標準エラー出力（basicConfigの既定）へ出す。MCPサーバーはstdioトランスポートで
    stdoutをプロトコル通信に使うため、stdoutには出さない。
    """
    logging.basicConfig(level=level, format=LOG_FORMAT)
    root = logging.getLogger()
    for handler in root.handlers:
        if not any(isinstance(f, SecretMaskingFilter) for f in handler.filters):
            handler.addFilter(SecretMaskingFilter())
    # リクエストURLを出力するライブラリロガーはWARNING以上に抑制する（Filterとの併用）
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
