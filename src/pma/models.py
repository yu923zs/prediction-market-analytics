"""Unified data model shared by all connectors and the storage layer."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple


def utc_now_iso() -> str:
    """Current UTC time as an ISO-8601 string with Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def unix_to_iso(unix_seconds: int) -> str:
    return datetime.fromtimestamp(unix_seconds, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


@dataclass
class MarketSnapshot:
    """One observation of one market at one point in time (unified schema).

    prob is the implied YES probability in [0, 1]:
      - Polymarket: YES outcome price from the Gamma API.
      - Kalshi: last trade price, else mid of yes_bid/yes_ask, in cents / 100.
    volume_24h is USD-equivalent (for Kalshi, contracts traded x price, a
    documented approximation).
    """

    ts: str                       # UTC ISO-8601, e.g. 2026-10-04T08:00:00Z
    platform: str                 # "polymarket" | "kalshi"
    market_id: str                # native id (gamma market id / kalshi ticker)
    question: str
    prob: Optional[float]
    bid: Optional[float] = None
    ask: Optional[float] = None
    volume_24h: Optional[float] = None      # USD-equivalent
    volume_native: Optional[float] = None   # native units (contracts / shares)
    liquidity: Optional[float] = None       # USD
    end_date: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    KEY_FIELDS = (
        "ts", "platform", "market_id", "question", "prob", "bid", "ask",
        "volume_24h", "volume_native", "liquidity", "end_date",
    )

    def row(self) -> Tuple:
        """Values in DB column order (see storage.SCHEMA)."""
        return tuple(getattr(self, k) for k in self.KEY_FIELDS)

    def to_dict(self) -> Dict[str, Any]:
        d = {k: getattr(self, k) for k in self.KEY_FIELDS}
        d["extra"] = self.extra
        return d
