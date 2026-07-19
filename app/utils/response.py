"""Helpers to build the standard `{success, data, message, error}` envelope."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value


def ok(data: Any = None, message: str | None = None) -> dict[str, Any]:
    return {
        "success": True,
        "data": _to_jsonable(data),
        "message": message,
        "error": None,
    }


def fail(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "success": False,
        "data": None,
        "message": None,
        "error": {"code": code, "message": message, "details": details or {}},
    }
