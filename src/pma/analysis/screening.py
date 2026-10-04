"""Step 1 of the analysis framework: which markets are worth watching?

Criterion: 24h USD-equivalent volume above a floor, ranked descending.
Volume is a simple, transparent proxy for attention and liquidity.
"""
from __future__ import annotations

from typing import List

from pma.models import MarketSnapshot


def select_top_markets(snaps: List[MarketSnapshot],
                       min_volume_24h_usd: float,
                       top_n: int) -> List[MarketSnapshot]:
    eligible = [s for s in snaps if (s.volume_24h or 0.0) >= min_volume_24h_usd]
    eligible.sort(key=lambda s: s.volume_24h or 0.0, reverse=True)
    return eligible[:top_n]
