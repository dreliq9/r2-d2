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


def _default_collection_path() -> Path:
    from_env = os.getenv("SWU_MCP_COLLECTION_PATH")
    if from_env:
        return Path(from_env).expanduser()
    return Path.home() / ".swu-mcp" / "collection.json"


def _default_cache_dir() -> Path:
    from_env = os.getenv("SWU_MCP_CACHE_DIR")
    if from_env:
        return Path(from_env).expanduser()
    # Anchor to the project root so the resolved path is independent of CWD.
    # Without this, an MCP server launched from any directory looks for the
    # cache relative to its launching shell's CWD (usually $HOME).
    return Path(__file__).resolve().parent.parent.parent / ".swu-mcp-cache"


@dataclass(frozen=True)
class Settings:
    api_base_url: str = os.getenv("SWU_MCP_API_BASE_URL", "https://api.swu-db.com")
    card_catalog_path: str | None = _default_catalog_path()
    cache_dir: Path = _default_cache_dir()
    default_limit: int = int(os.getenv("SWU_MCP_DEFAULT_LIMIT", "10"))
    collection_path: Path = _default_collection_path()


settings = Settings()
