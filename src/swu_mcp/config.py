from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _default_catalog_path() -> str:
    from_env = os.getenv("SWU_MCP_CARD_CATALOG_PATH")
    if from_env:
        return from_env
    bundled = Path(__file__).resolve().parent.parent.parent / "data" / "catalog" / "cards.json"
    if bundled.exists():
        return str(bundled)
    return None


@dataclass(frozen=True)
class Settings:
    api_base_url: str = os.getenv("SWU_MCP_API_BASE_URL", "https://api.swu-db.com")
    card_catalog_path: str | None = _default_catalog_path()
    cache_dir: Path = Path(os.getenv("SWU_MCP_CACHE_DIR", ".swu-mcp-cache"))
    default_limit: int = int(os.getenv("SWU_MCP_DEFAULT_LIMIT", "10"))


settings = Settings()
