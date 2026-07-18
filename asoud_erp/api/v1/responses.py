from typing import Any


def success(data: Any = None, meta: dict[str, Any] | None = None) -> dict:
    response_meta = {"api_version": "v1"}
    if meta:
        response_meta.update(meta)
    return {"ok": True, "data": data, "meta": response_meta}


def failure(code: str, message: str) -> dict:
    return {
        "ok": False,
        "error": {"code": code, "message": message},
        "meta": {"api_version": "v1"},
    }

