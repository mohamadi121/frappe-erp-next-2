"""A small client for the Gemloy "Gemma Messages API" (Anthropic wire format).

The model is Gemma 4 26B (4-bit) served privately. The base URL and the API key
are read from the site config keys ``gemloy_base_url`` and ``gemloy_api_key``;
they are never hard-coded, never logged and never placed in an error message or
an audit row. The operator may retain request/response bodies, so the caller
(or the orchestrator) is responsible for masking sensitive values before they
are sent.

Only the standard library is used (``urllib``). The transport is injectable so
the pure tests run against a fake transport and never touch the network.
"""

import json
import secrets
import time
import urllib.error
import urllib.request

MODEL = "gemma4-26b"

# The service runs 2 generations at a time and each key has its own rate limit
# (60 rpm). A 429 ``rate_limit_error`` (and a 529 ``overloaded_error`` while the
# model is loading) carries a ``Retry-After`` and is worth one bounded retry; a
# 429 ``quota_exceeded_error`` has no Retry-After and must never be retried.
_RETRYABLE = {("429", "rate_limit_error"), ("529", "overloaded_error")}
_RETRY_AFTER_CAP = 30.0
_DEFAULT_RETRY_AFTER = 2.0

# Persian, user-facing. The key and the raw body are never part of these.
_NOT_CONFIGURED = "دستیار هوشمند پیکربندی نشده است"
_RATE_LIMITED = "درخواست‌ها بیش از حد مجاز است؛ کمی بعد دوباره تلاش کنید."
_QUOTA_EXCEEDED = "سقف اعتبار سرویس هوش مصنوعی تمام شده است."
_UNAUTHORIZED = "کلید سرویس هوش مصنوعی نامعتبر است."
_UNREACHABLE = "اتصال به سرویس هوش مصنوعی برقرار نشد."
_API_ERROR = "خطا در سرویس هوش مصنوعی."


class GemloyError(Exception):
    """A failed call to the Gemloy API. The message is a safe Persian sentence."""


def _request_id() -> str:
    # 1-128 chars of [A-Za-z0-9_-]; 32 hex chars is well inside that.
    return secrets.token_hex(16)


def _retry_after(headers: dict) -> float:
    raw = headers.get("Retry-After") or headers.get("retry-after")
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        value = _DEFAULT_RETRY_AFTER
    return max(0.0, min(value, _RETRY_AFTER_CAP))


def _error_message(status: int, error_type: str | None) -> str:
    if error_type == "quota_exceeded_error":
        return _QUOTA_EXCEEDED
    if error_type == "rate_limit_error":
        return _RATE_LIMITED
    if status == 401 or error_type == "authentication_error":
        return _UNAUTHORIZED
    return _API_ERROR


def _parse_error(body: bytes) -> dict | None:
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _urllib_transport(url: str, headers: dict, body: bytes, timeout: float) -> tuple[int, dict, bytes]:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers or {}), exc.read()
    except (urllib.error.URLError, TimeoutError, OSError):
        raise GemloyError(_UNREACHABLE) from None


class GemloyClient:
    def __init__(self, base_url: str, api_key: str, *, transport=None, timeout: float = 60.0,
                 max_retries: int = 2, sleep=time.sleep):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._transport = transport or _urllib_transport
        self._timeout = timeout
        self._max_retries = max(0, int(max_retries))
        self._sleep = sleep

    @classmethod
    def from_site_config(cls, *, transport=None, timeout: float = 60.0, max_retries: int = 2,
                         sleep=time.sleep) -> "GemloyClient":
        import frappe

        base_url = str(frappe.conf.get("gemloy_base_url") or "").strip()
        api_key = str(frappe.conf.get("gemloy_api_key") or "").strip()
        if not base_url or not api_key:
            raise ValueError(_NOT_CONFIGURED)
        return cls(base_url, api_key, transport=transport, timeout=timeout,
                   max_retries=max_retries, sleep=sleep)

    def _post(self, path: str, payload: dict, request_id: str | None) -> dict:
        url = self._base_url + path
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "content-type": "application/json",
            "x-api-key": self._api_key,
            "request-id": request_id or _request_id(),
        }
        attempts = self._max_retries + 1
        for attempt in range(attempts):
            status, resp_headers, resp_body = self._transport(url, headers, body, self._timeout)
            if 200 <= status < 300:
                return json.loads(resp_body.decode("utf-8"))
            error = _parse_error(resp_body)
            error_type = (error.get("error") or {}).get("type") if isinstance(error, dict) else None
            if (str(status), error_type) in _RETRYABLE and attempt < self._max_retries:
                self._sleep(_retry_after(resp_headers))
                continue
            raise GemloyError(_error_message(status, error_type))
        raise GemloyError(_RATE_LIMITED)  # pragma: no cover - loop always returns or raises

    def create_message(self, messages: list, *, system: str | None = None, max_tokens: int = 1024,
                       temperature: float = 0.2, tools: list | None = None,
                       tool_choice: dict | None = None, thinking: dict | None = None,
                       model: str = MODEL, request_id: str | None = None) -> dict:
        payload: dict = {"model": model, "messages": messages, "max_tokens": max_tokens,
                         "temperature": temperature}
        if system is not None:
            payload["system"] = system
        if tools:
            payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        if thinking is not None:
            payload["thinking"] = thinking
        return self._post("/v1/messages", payload, request_id)

    def count_tokens(self, messages: list, *, system: str | None = None, tools: list | None = None,
                     model: str = MODEL, request_id: str | None = None) -> int:
        payload: dict = {"model": model, "messages": messages}
        if system is not None:
            payload["system"] = system
        if tools:
            payload["tools"] = tools
        parsed = self._post("/v1/messages/count_tokens", payload, request_id)
        return int(parsed.get("input_tokens", 0))


def extract_text(content: list) -> str:
    """The assistant text: the block(s) with ``type == "text"``.

    A ``thinking`` block may come first, so ``content[0]`` must never be read
    blindly.
    """
    parts = [block.get("text", "") for block in (content or [])
             if isinstance(block, dict) and block.get("type") == "text"]
    return "".join(parts)


def tool_use_blocks(content: list) -> list[dict]:
    """The ``tool_use`` blocks (id, name, input) in order."""
    return [block for block in (content or [])
            if isinstance(block, dict) and block.get("type") == "tool_use"]
