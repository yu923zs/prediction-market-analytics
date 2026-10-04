"""Central configuration: sane defaults, overridable via environment / .env."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv is optional
    def load_dotenv(*args, **kwargs):  # type: ignore[misc]
        return False

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


@dataclass
class Config:
    # storage
    db_path: Path = PROJECT_ROOT / "data" / "markets.db"
    outputs_dir: Path = PROJECT_ROOT / "outputs"

    # ingestion
    top_n_markets: int = 15
    polymarket_pages: int = 3          # 3 x 100 markets scanned, ranked client-side
    page_size: int = 100
    request_timeout: int = 30

    # screening
    min_volume_24h_usd: float = 10_000.0

    # tracking
    change_window_minutes: int = 60

    # anomaly detection
    jump_threshold: float = 0.05        # >= 5pp move between consecutive points
    volume_spike_ratio: float = 1.5     # volume_24h >= 1.5x its rolling baseline
    volume_spike_min_abs: float = 5_000.0
    divergence_threshold: float = 0.08  # cross-platform prob gap > 8pp
    match_jaccard: float = 0.55         # min question-text similarity to match

    # agent
    llm_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com")
    llm_api_key: str = (os.getenv("OPENAI_API_KEY")
                        or os.getenv("DEEPSEEK_API_KEY") or "")
    llm_model: str = os.getenv("OPENAI_MODEL", "deepseek-chat")
    llm_timeout: int = 60
