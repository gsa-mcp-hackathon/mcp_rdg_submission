"""Environment-based configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class Settings:
    server_hostname: str
    http_path: str
    access_token: str
    max_preview_rows: int = 100

    @classmethod
    def from_env(cls) -> "Settings":
        host = os.getenv("DATABRICKS_HOST", "").strip()
        http_path = os.getenv("DATABRICKS_HTTP_PATH", "").strip()
        token = os.getenv("DATABRICKS_TOKEN", "").strip()

        missing = [
            name
            for name, value in (
                ("DATABRICKS_HOST", host),
                ("DATABRICKS_HTTP_PATH", http_path),
                ("DATABRICKS_TOKEN", token),
            )
            if not value
        ]
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

        if "://" in host:
            parsed = urlparse(host)
            if parsed.scheme != "https" or not parsed.hostname:
                raise ValueError("DATABRICKS_HOST must be a hostname or an https URL")
            host = parsed.hostname
        else:
            host = host.rstrip("/")

        raw_limit = os.getenv("MCP_RDG_MAX_PREVIEW_ROWS", "100")
        try:
            max_preview_rows = int(raw_limit)
        except ValueError as exc:
            raise ValueError("MCP_RDG_MAX_PREVIEW_ROWS must be an integer") from exc
        if not 1 <= max_preview_rows <= 1000:
            raise ValueError("MCP_RDG_MAX_PREVIEW_ROWS must be between 1 and 1000")

        return cls(host, http_path, token, max_preview_rows)

