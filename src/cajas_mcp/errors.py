from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CajasMcpError(Exception):
    code: str
    message: str
    status_code: int | None = None
    retryable: bool = False
    requires_user_action: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "requires_user_action": self.requires_user_action,
            "details": self.details,
        }


def normalize_http_status(status_code: int, message: str, details: dict[str, Any] | None = None) -> CajasMcpError:
    if status_code == 401:
        return CajasMcpError("AUTH_REQUIRED", message, status_code, requires_user_action=True, details=details or {})
    if status_code == 403:
        return CajasMcpError("PERMISSION_DENIED", message, status_code, requires_user_action=True, details=details or {})
    if status_code == 404:
        return CajasMcpError("RESOURCE_NOT_FOUND", message, status_code, requires_user_action=True, details=details or {})
    if status_code == 429:
        return CajasMcpError("RATE_LIMITED", message, status_code, retryable=True, details=details or {})
    if status_code >= 500:
        return CajasMcpError("CAJAS_API_UNAVAILABLE", message, status_code, retryable=True, details=details or {})
    return CajasMcpError("INVALID_INPUT", message, status_code, requires_user_action=True, details=details or {})


def ok(data: dict[str, Any], *, explanation: str = "", warnings: list[str] | None = None, request_id: str | None = None) -> dict[str, Any]:
    return {
        "ok": True,
        "data": data,
        "warnings": warnings or [],
        "explanation": explanation,
        "request_id": request_id,
    }


def error_payload(error: CajasMcpError, *, request_id: str | None = None) -> dict[str, Any]:
    return {"ok": False, "error": error.to_payload(), "request_id": request_id}

