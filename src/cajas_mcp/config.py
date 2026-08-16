from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse


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


def _csv_env(name: str) -> list[str]:
    raw = os.getenv(name)
    if raw is None:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    cajas_api_base_url: str
    env: str = "development"
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
    stackexchange_max_queries: int = 4
    stackexchange_max_search_requests: int = 4
    stackexchange_max_evidence_items: int = 4
    stackexchange_max_answers_per_question: int = 2
    external_timeout: float = 10.0
    external_cache_ttl: int = 3600
    max_recommendation_raw_entries: int = 50
    max_file_bytes: int = 5 * 1024 * 1024
    max_workbook_sheets: int = 10
    max_rows: int = 5000
    max_columns: int = 100
    max_cell_length: int = 5000
    import_session_ttl: int = 1800
    allowed_hosts: tuple[str, ...] = ()
    allowed_origins: tuple[str, ...] = ()
    auth_enabled: bool = False
    auth_issuer_url: str | None = None
    auth_resource_url: str | None = None
    oauth_scopes_supported: tuple[str, ...] = ()
    oauth_required_scopes: tuple[str, ...] = ()
    session_secret: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        public_url = os.getenv("CAJAS_MCP_PUBLIC_URL", "https://sebit-mcp.com").rstrip("/")
        configured_hosts = _csv_env("CAJAS_MCP_ALLOWED_HOSTS")
        configured_origins = _csv_env("CAJAS_MCP_ALLOWED_ORIGINS")
        env = os.getenv("CAJAS_MCP_ENV", "development").strip().lower() or "development"
        shared_token = os.getenv("CAJAS_API_BEARER_TOKEN") or None
        auth_resource_url = os.getenv("CAJAS_MCP_AUTH_RESOURCE_URL") or f"{public_url}/mcp"
        return cls(
            env=env,
            cajas_api_base_url=os.getenv("CAJAS_API_BASE_URL", "").rstrip("/"),
            public_url=public_url,
            transport=os.getenv("CAJAS_MCP_TRANSPORT", "streamable-http"),
            log_level=os.getenv("CAJAS_MCP_LOG_LEVEL", "INFO").upper(),
            mcp_path=os.getenv("CAJAS_MCP_PATH", "/mcp"),
            cajas_api_bearer_token=shared_token,
            http_timeout=float(os.getenv("CAJAS_HTTP_TIMEOUT", "30")),
            http_retries=_int_env("CAJAS_HTTP_RETRIES", 2),
            stackexchange_enabled=_bool_env("STACKEXCHANGE_ENABLED", False),
            stackexchange_key=os.getenv("STACKEXCHANGE_KEY") or None,
            stackexchange_site=os.getenv("STACKEXCHANGE_SITE", "stackoverflow"),
            stackexchange_max_queries=_int_env("STACKEXCHANGE_MAX_QUERIES", 4),
            stackexchange_max_search_requests=_int_env("STACKEXCHANGE_MAX_SEARCH_REQUESTS", 4),
            stackexchange_max_evidence_items=_int_env("STACKEXCHANGE_MAX_EVIDENCE_ITEMS", 4),
            stackexchange_max_answers_per_question=_int_env("STACKEXCHANGE_MAX_ANSWERS_PER_QUESTION", 2),
            external_timeout=float(os.getenv("EXTERNAL_CONTEXT_TIMEOUT", "10")),
            external_cache_ttl=_int_env("EXTERNAL_CONTEXT_CACHE_TTL", 3600),
            max_recommendation_raw_entries=_int_env("CAJAS_MAX_RECOMMENDATION_RAW_ENTRIES", 50),
            max_file_bytes=_int_env("CAJAS_MAX_FILE_BYTES", 5 * 1024 * 1024),
            max_workbook_sheets=_int_env("CAJAS_MAX_WORKBOOK_SHEETS", 10),
            max_rows=_int_env("CAJAS_MAX_IMPORT_ROWS", 5000),
            max_columns=_int_env("CAJAS_MAX_IMPORT_COLUMNS", 100),
            max_cell_length=_int_env("CAJAS_MAX_CELL_LENGTH", 5000),
            import_session_ttl=_int_env("CAJAS_IMPORT_SESSION_TTL", 1800),
            allowed_hosts=tuple(configured_hosts or _default_allowed_hosts(public_url)),
            allowed_origins=tuple(configured_origins or _default_allowed_origins(public_url)),
            auth_enabled=_bool_env("CAJAS_MCP_AUTH_ENABLED", False),
            auth_issuer_url=os.getenv("CAJAS_MCP_AUTH_ISSUER_URL") or None,
            auth_resource_url=auth_resource_url,
            oauth_scopes_supported=tuple(
                _csv_env("CAJAS_MCP_OAUTH_SCOPES_SUPPORTED")
                or ["cajas:read"]
            ),
            oauth_required_scopes=tuple(_csv_env("CAJAS_MCP_OAUTH_REQUIRED_SCOPES") or ["cajas:read"]),
            session_secret=os.getenv("CAJAS_MCP_SESSION_SECRET") or None,
        )

    def validate_ready(self) -> list[str]:
        missing: list[str] = []
        if not self.cajas_api_base_url:
            missing.append("CAJAS_API_BASE_URL")
        if self.auth_enabled and not self.auth_issuer_url:
            missing.append("CAJAS_MCP_AUTH_ISSUER_URL")
        return missing

    def validate_startup(self) -> None:
        if self.env == "production" and self.cajas_api_bearer_token:
            raise RuntimeError("CAJAS_API_BEARER_TOKEN is not allowed when CAJAS_MCP_ENV=production.")
        if self.auth_enabled and not self.auth_issuer_url:
            raise RuntimeError("CAJAS_MCP_AUTH_ISSUER_URL is required when CAJAS_MCP_AUTH_ENABLED=true.")


def _default_allowed_hosts(public_url: str) -> list[str]:
    hosts = ["localhost:*", "127.0.0.1:*", "[::1]:*"]
    parsed = urlparse(public_url if "://" in public_url else f"https://{public_url}")
    if parsed.hostname:
        hosts.append(parsed.hostname)
        hosts.append(f"{parsed.hostname}:*")
    return _dedupe(hosts)


def _default_allowed_origins(public_url: str) -> list[str]:
    origins = ["http://localhost:*", "http://127.0.0.1:*"]
    parsed = urlparse(public_url if "://" in public_url else f"https://{public_url}")
    if parsed.scheme and parsed.hostname:
        origins.append(f"{parsed.scheme}://{parsed.hostname}")
    return _dedupe(origins)


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value not in out:
            out.append(value)
    return out
