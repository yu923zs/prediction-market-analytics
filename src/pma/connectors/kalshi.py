"""Kalshi connector (https://api.elections.kalshi.com/trade-api/v2).

Kalshi's REST API requires request signing (RSA-PSS over
timestamp + METHOD + path). Credentials are optional at the framework level:
without KALSHI_API_KEY_ID + KALSHI_PRIVATE_KEY_PATH the connector raises
AuthRequiredError and the pipeline continues with Polymarket only.

Prices are in cents (1-99); prob = price / 100. volume_24h is in contracts;
USD-equivalent volume is approximated as contracts x price (each contract
pays $1 at settlement).
"""
from __future__ import annotations

import base64
import logging
import os
from datetime import datetime, timezone
from typing import List, Optional

from pma.connectors.base import AuthRequiredError, BaseConnector
from pma.models import MarketSnapshot, utc_now_iso

log = logging.getLogger(__name__)

API_BASE = "https://api.elections.kalshi.com/trade-api/v2"
MARKETS_PATH = "/trade-api/v2/markets"


class KalshiConnector(BaseConnector):
    platform = "kalshi"

    def __init__(self, timeout: int = 30, pages: int = 3, page_size: int = 100):
        super().__init__(timeout, pages, page_size)
        self.key_id = os.getenv("KALSHI_API_KEY_ID", "")
        key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH", "")
        self.private_key = None
        if self.key_id and key_path:
            from cryptography.hazmat.primitives import serialization
            with open(key_path, "rb") as f:
                self.private_key = serialization.load_pem_private_key(
                    f.read(), password=None)

    def _auth_headers(self) -> dict:
        if not self.private_key:
            raise AuthRequiredError(
                "kalshi: credentials not configured "
                "(set KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY_PATH)")
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        ts_ms = str(int(datetime.now(timezone.utc).timestamp() * 1000))
        msg = f"{ts_ms}GET{MARKETS_PATH}".encode()
        sig = self.private_key.sign(
            msg,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                        salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256(),
        )
        return {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode(),
            "KALSHI-ACCESS-TIMESTAMP": ts_ms,
        }

    @staticmethod
    def _to_float(value) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def fetch_markets(self, top_n: int) -> List[MarketSnapshot]:
        headers = self._auth_headers() if self.private_key else None
        data = self.get_json(f"{API_BASE}/markets",
                             params={"status": "open", "limit": 1000},
                             headers=headers)
        raw = data.get("markets", [])
        log.info("kalshi: fetched %d raw markets", len(raw))

        ts = utc_now_iso()
        snaps: List[MarketSnapshot] = []
        for m in raw:
            last = self._to_float(m.get("last_price"))
            bid = self._to_float(m.get("yes_bid"))
            ask = self._to_float(m.get("yes_ask"))
            if last is not None and 0 < last < 100:
                prob = last / 100.0
            elif bid is not None and ask is not None and 0 < bid <= ask < 100:
                prob = (bid + ask) / 200.0
            else:
                continue
            # USD-equivalent 24h volume: contracts traded x implied price
            vol_contracts = self._to_float(m.get("volume_24h")) or 0.0
            snaps.append(MarketSnapshot(
                ts=ts,
                platform=self.platform,
                market_id=m.get("ticker") or "",
                question=m.get("title") or "",
                prob=prob,
                bid=bid / 100.0 if bid is not None else None,
                ask=ask / 100.0 if ask is not None else None,
                volume_24h=vol_contracts * prob,
                volume_native=vol_contracts,
                liquidity=(self._to_float(m.get("liquidity")) or 0.0) / 100.0,
                end_date=m.get("close_time"),
                extra={"event_ticker": m.get("event_ticker")},
            ))

        snaps.sort(key=lambda s: s.volume_24h or 0.0, reverse=True)
        return snaps[:top_n]
