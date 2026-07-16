from typing import Any


def success(data: Any = None) -> dict:
    return {"ok": True, "data": data, "meta": {"api_version": "v1"}}


def failure(code: str, message: str) -> dict:
    return {
        "ok": False,
        "error": {"code": code, "message": message},
        "meta": {"api_version": "v1"},
    }

