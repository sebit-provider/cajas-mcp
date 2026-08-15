from __future__ import annotations

import os
from dataclasses import dataclass


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    cajas_api_base_url: str
    public_url: str = "https://sebit-mcp.com"
    transport: str = "streamable-http"
    log_level: str = "INFO"
    mcp_path: str = "/mcp"
    cajas_api_bearer_token: str | None = None
    http_timeout: float = 30.0
    http_retries: int = 2
    stackexchange_enabled: bool = False
    stackexchange_key: str | None = None
    stackexchange_site: str = "stackoverflow"
    external_timeout: float = 10.0
    external_cache_ttl: int = 3600
    max_recommendation_raw_entries: int = 50

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            cajas_api_base_url=os.getenv("CAJAS_API_BASE_URL", "").rstrip("/"),
            public_url=os.getenv("CAJAS_MCP_PUBLIC_URL", "https://sebit-mcp.com").rstrip("/"),
            transport=os.getenv("CAJAS_MCP_TRANSPORT", "streamable-http"),
            log_level=os.getenv("CAJAS_MCP_LOG_LEVEL", "INFO").upper(),
            mcp_path=os.getenv("CAJAS_MCP_PATH", "/mcp"),
            cajas_api_bearer_token=os.getenv("CAJAS_API_BEARER_TOKEN") or None,
            http_timeout=float(os.getenv("CAJAS_HTTP_TIMEOUT", "30")),
            http_retries=_int_env("CAJAS_HTTP_RETRIES", 2),
            stackexchange_enabled=_bool_env("STACKEXCHANGE_ENABLED", False),
            stackexchange_key=os.getenv("STACKEXCHANGE_KEY") or None,
            stackexchange_site=os.getenv("STACKEXCHANGE_SITE", "stackoverflow"),
            external_timeout=float(os.getenv("EXTERNAL_CONTEXT_TIMEOUT", "10")),
            external_cache_ttl=_int_env("EXTERNAL_CONTEXT_CACHE_TTL", 3600),
            max_recommendation_raw_entries=_int_env("CAJAS_MAX_RECOMMENDATION_RAW_ENTRIES", 50),
        )

    def validate_ready(self) -> list[str]:
        missing: list[str] = []
        if not self.cajas_api_base_url:
            missing.append("CAJAS_API_BASE_URL")
        return missing

