from typing import Any


def success(data: Any = None, meta: dict[str, Any] | None = None) -> dict:
    response_meta = {"api_version": "v1"}
    if meta:
        response_meta.update(meta)
    return {"ok": True, "data": data, "meta": response_meta}


def failure(code: str, message: str, *, retryable: bool | None = None, field: str | None = None,
            hint: str | None = None) -> dict:
    """The ``ok: false`` envelope.

    ``retryable``, ``field`` and ``hint`` are additive: each key is present in the
    ``error`` object only when the caller passes it, so existing callers and the
    ``ok/data/meta/error`` envelope are unchanged. ``retryable`` must be derived by
    the caller from the status class (429 / 5xx / ``REQUEST_IN_PROGRESS``), never
    from the message text.
    """
    error: dict[str, Any] = {"code": code, "message": message}
    if retryable is not None:
        error["retryable"] = retryable
    if field is not None:
        error["field"] = field
    if hint is not None:
        error["hint"] = hint
    return {"ok": False, "error": error, "meta": {"api_version": "v1"}}

