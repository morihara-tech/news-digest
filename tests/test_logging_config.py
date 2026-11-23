from __future__ import annotations

import io
import logging
import sys

import httpx
import pytest

from src.config import DeliveryTargetConfig
from src.core.delivery import DeliveryError, DeliveryTarget, deliver_digest, send_webhook
from src.core.digest import DigestResult
from src.logging_config import SecretMaskingFilter, mask_secrets, register_secret, setup_logging

GCHAT_URL = "https://chat.googleapis.com/v1/spaces/DUMMYSPACE/messages?key=DUMMYKEY&token=DUMMYTOKEN"
SLACK_URL = "https://hooks.slack.com/services/TDUMMY/BDUMMY/DUMMYSECRET"
SECRETS = ["DUMMYSPACE", "DUMMYKEY", "DUMMYTOKEN", "TDUMMY", "BDUMMY", "DUMMYSECRET"]


def _assert_clean(text: str) -> None:
    for secret in SECRETS:
        assert secret not in text, f"{secret} が漏れている: {text}"


@pytest.fixture
def masked_stream():
    """Filter付きハンドラを持つ専用ロガーと、その出力先を返す。"""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    handler.addFilter(SecretMaskingFilter())
    root = logging.getLogger()
    old_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    yield stream
    root.removeHandler(handler)
    root.setLevel(old_level)


@pytest.mark.parametrize("url", [GCHAT_URL, SLACK_URL])
@pytest.mark.parametrize("level", [logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR])
def test_filter_masks_url_in_all_levels(masked_stream, url, level):
    # httpxのリクエストログと同形式（子ロガーからルートハンドラへ伝播。httpxロガー自体のWARNING化には依存しない）
    logging.getLogger("thirdparty.http").log(level, 'HTTP Request: POST %s "HTTP/1.1 200 OK"', url)
    out = masked_stream.getvalue()
    _assert_clean(out)
    assert "HTTP Request: POST" in out
    assert ("https://chat.googleapis.com/***" in out) or ("https://hooks.slack.com/***" in out)
    assert "200 OK" in out


def test_filter_masks_exc_info(masked_stream):
    try:
        raise RuntimeError(f"Client error '403 Forbidden' for url '{GCHAT_URL}'")
    except RuntimeError:
        logging.getLogger("app").exception("failed")
    out = masked_stream.getvalue()
    _assert_clean(out)
    assert "Traceback" in out
    assert "chat.googleapis.com" in out


def test_filter_masks_exception_chain(masked_stream):
    try:
        try:
            raise ValueError(f"inner {SLACK_URL}")
        except ValueError as inner:
            raise RuntimeError("outer") from inner
    except RuntimeError:
        logging.getLogger("app").error("boom", exc_info=True)
    _assert_clean(masked_stream.getvalue())


def test_filter_masks_args_and_stack_info(masked_stream):
    logging.getLogger("app").warning("url=%s", GCHAT_URL, stack_info=True)
    _assert_clean(masked_stream.getvalue())


def test_mask_secrets_query_and_encoded_forms():
    assert "SECRETVAL" not in mask_secrets("https://example.com/x?a=1&token=SECRETVAL")
    assert "SECRETVAL" not in mask_secrets("https://example.com/x?key=SECRETVAL&a=1")
    assert "SECRETVAL" not in mask_secrets("redirect=https%3A%2F%2Fexample.com%2Fx%3Ftoken%3DSECRETVAL")
    assert "DUMMYKEY" not in mask_secrets(
        "https%3A%2F%2Fchat.googleapis.com%2Fv1%2Fspaces%2FS%2Fmessages%3Fkey%3DDUMMYKEY"
    )
    assert "SECRETVAL" not in mask_secrets("Authorization: Bearer SECRETVAL")
    assert "SECRETVAL" not in mask_secrets("headers={'x-api-key': 'SECRETVAL'}")
    assert "sk-ant-api03-abc" not in mask_secrets("key sk-ant-api03-abc_DEF")


def test_mask_secrets_keeps_plain_text():
    assert mask_secrets("通常のログ https://example.com/a?page=2") == "通常のログ https://example.com/a?page=2"


def test_registered_secret_is_masked_by_exact_match():
    register_secret("https://webhook.internal.example/path/SUPERSECRETVALUE")
    out = mask_secrets("post to https://webhook.internal.example/path/SUPERSECRETVALUE done")
    assert "SUPERSECRETVALUE" not in out


def _mock_post(status: int):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, request=request)

    def fake_post(url, json=None, timeout=None):
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            return client.post(url, json=json, timeout=timeout)

    return fake_post


@pytest.mark.parametrize("url", [GCHAT_URL, SLACK_URL])
def test_send_webhook_error_message_has_no_url(monkeypatch, url):
    monkeypatch.setattr(httpx, "post", _mock_post(403))
    target = DeliveryTarget(
        config=DeliveryTargetConfig(name="t", format="google_chat", webhook_url_env="X"),
        webhook_url=url,
    )
    with pytest.raises(DeliveryError) as excinfo:
        send_webhook(target, {"text": "x"})
    _assert_clean(str(excinfo.value))
    assert "403" in str(excinfo.value)
    assert excinfo.value.__cause__ is None


def test_send_webhook_transport_error_has_no_url(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        raise httpx.ConnectError(f"cannot connect to {url}", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    target = DeliveryTarget(
        config=DeliveryTargetConfig(name="t", format="google_chat", webhook_url_env="X"),
        webhook_url=GCHAT_URL,
    )
    with pytest.raises(DeliveryError) as excinfo:
        send_webhook(target, {"text": "x"})
    _assert_clean(str(excinfo.value))


def test_deliver_digest_logs_and_error_have_no_secret(monkeypatch, caplog):
    monkeypatch.setattr(httpx, "post", _mock_post(403))
    target = DeliveryTarget(
        config=DeliveryTargetConfig(name="gchat", format="google_chat", webhook_url_env="X"),
        webhook_url=GCHAT_URL,
    )
    with caplog.at_level(logging.INFO), pytest.raises(DeliveryError) as excinfo:
        deliver_digest([target], DigestResult(articles=[], groups={}))
    _assert_clean(str(excinfo.value))
    _assert_clean(caplog.text)


def test_real_httpx_request_log_is_masked(monkeypatch, masked_stream):
    """httpxが実際に出すINFOログ行（MockTransport経由、ネットワーク不使用）がマスクされる。"""
    logging.getLogger("httpx").setLevel(logging.INFO)
    try:
        monkeypatch.setattr(httpx, "post", _mock_post(200))
        target = DeliveryTarget(
            config=DeliveryTargetConfig(name="gchat", format="google_chat", webhook_url_env="X"),
            webhook_url=GCHAT_URL,
        )
        send_webhook(target, {"text": "x"})
    finally:
        logging.getLogger("httpx").setLevel(logging.WARNING)
    out = masked_stream.getvalue()
    assert "HTTP Request: POST" in out
    _assert_clean(out)


def test_setup_logging_is_idempotent_and_targets_stderr():
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    root.handlers = []
    try:
        setup_logging()
        setup_logging()
        assert len(root.handlers) == 1
        handler = root.handlers[0]
        assert [type(f) for f in handler.filters] == [SecretMaskingFilter]
        assert handler.stream is sys.stderr
        assert logging.getLogger("httpx").level == logging.WARNING
        assert logging.getLogger("httpcore").level == logging.WARNING
    finally:
        root.handlers = saved_handlers
        root.setLevel(saved_level)


def test_setup_logging_attaches_filter_to_existing_handlers():
    root = logging.getLogger()
    handler = logging.StreamHandler(io.StringIO())
    root.addHandler(handler)
    try:
        setup_logging()
        setup_logging()
        assert sum(isinstance(f, SecretMaskingFilter) for f in handler.filters) == 1
    finally:
        root.removeHandler(handler)


def test_cli_and_server_call_setup_logging(monkeypatch):
    import importlib

    import src.logging_config as lc

    calls: list[str] = []
    monkeypatch.setattr(lc, "setup_logging", lambda *a, **k: calls.append("called"))
    for mod_name in ("src.cli", "src.server"):
        sys.modules.pop(mod_name, None)
        importlib.import_module(mod_name)
    assert calls == ["called", "called"]
    # monkeypatch解除後のモジュール状態を実関数で再ロードしておく
    monkeypatch.undo()
    for mod_name in ("src.cli", "src.server"):
        sys.modules.pop(mod_name, None)
