"""Polymarket connector.

- Gamma API (https://gamma-api.polymarket.com): market discovery and metadata,
  no authentication required.
- CLOB API (https://clob.polymarket.com/prices-history): historical probability
  series for backfill, no authentication required for public reads.
"""
from __future__ import annotations

import json
import logging
from typing import List, Optional

from pma.connectors.base import BaseConnector
from pma.models import MarketSnapshot, unix_to_iso, utc_now_iso

log = logging.getLogger(__name__)

GAMMA_URL = "https://gamma-api.polymarket.com/markets"
CLOB_HISTORY_URL = "https://clob.polymarket.com/prices-history"


def _parse_jsonish(value) -> Optional[list]:
    """Gamma returns list-typed columns as JSON-encoded strings."""
    if value is None:
        return None
    if isinstance(value, list):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _to_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class PolymarketConnector(BaseConnector):
    platform = "polymarket"

    def fetch_markets(self, top_n: int) -> List[MarketSnapshot]:
        raw: list = []
        for page in range(self.pages):
            offset = page * self.page_size
            data = self.get_json(GAMMA_URL, params={
                "active": "true", "closed": "false",
                "limit": self.page_size, "offset": offset,
            })
            batch = data if isinstance(data, list) else data.get("markets", [])
            raw.extend(batch)
            if len(batch) < self.page_size:
                break
        log.info("polymarket: fetched %d raw markets", len(raw))

        ts = utc_now_iso()
        snaps: List[MarketSnapshot] = []
        for m in raw:
            prices = _parse_jsonish(m.get("outcomePrices"))
            prob = _to_float(prices[0]) if prices else None  # YES price
            if prob is None:
                continue
            tokens = _parse_jsonish(m.get("clobTokenIds")) or []
            snaps.append(MarketSnapshot(
                ts=ts,
                platform=self.platform,
                market_id=str(m.get("id")),
                question=m.get("question") or "",
                prob=prob,
                volume_24h=_to_float(m.get("volume24hr")),
                liquidity=_to_float(m.get("liquidity")),
                end_date=m.get("endDate"),
                extra={"clob_token_id": tokens[0] if tokens else None,
                       "slug": m.get("slug")},
            ))

        snaps.sort(key=lambda s: s.volume_24h or 0.0, reverse=True)
        return snaps[:top_n]

    def fetch_price_history(self, clob_token_id: str,
                            interval: str = "1w", fidelity: int = 30) -> list:
        """Historical YES-price series: [{t: unix_seconds, p: price}, ...]."""
        data = self.get_json(CLOB_HISTORY_URL, params={
            "market": clob_token_id, "interval": interval,
            "fidelity": fidelity,
        })
        return data.get("history", [])

    def backfill_snapshots(self, snap: MarketSnapshot, interval: str = "1w",
                           fidelity: int = 30) -> List[MarketSnapshot]:
        """Expand a current snapshot into a historical prob series."""
        token = snap.extra.get("clob_token_id")
        if not token:
            return []
        out: List[MarketSnapshot] = []
        for point in self.fetch_price_history(token, interval, fidelity):
            out.append(MarketSnapshot(
                ts=unix_to_iso(int(point["t"])),
                platform=self.platform,
                market_id=snap.market_id,
                question=snap.question,
                prob=float(point["p"]),
                end_date=snap.end_date,
                extra={"clob_token_id": token, "backfilled": True},
            ))
        return out
