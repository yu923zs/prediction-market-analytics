"""Backfill historical probabilities for the top Polymarket markets.

Uses the public CLOB prices-history endpoint (no auth), so the tracking and
anomaly detectors have a real time series to work on immediately, even before
the live snapshot loop has accumulated history.

    python scripts/backfill_polymarket.py --top 10 --interval 1w --fidelity 30
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pma.config import Config                 # noqa: E402
from pma.connectors import PolymarketConnector  # noqa: E402
from pma.storage import Store                 # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top", type=int, default=10,
                        help="number of top-volume markets to backfill")
    parser.add_argument("--interval", default="1w",
                        help="history span: 1h/6h/1d/1w/1m/max (default 1w)")
    parser.add_argument("--fidelity", type=int, default=30,
                        help="resolution in minutes (default 30)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    cfg = Config()
    connector = PolymarketConnector(timeout=cfg.request_timeout,
                                    pages=cfg.polymarket_pages,
                                    page_size=cfg.page_size)

    snaps = connector.fetch_markets(top_n=args.top)
    print(f"backfilling {len(snaps)} markets "
          f"(interval={args.interval}, fidelity={args.fidelity}min)")

    total = 0
    with Store(cfg.db_path) as store:
        for s in snaps:
            historical = connector.backfill_snapshots(
                s, interval=args.interval, fidelity=args.fidelity)
            total += store.upsert(historical)
            print(f"  {s.market_id}: +{len(historical)} points "
                  f"| {s.question[:60]}")
            time.sleep(0.3)  # be polite to the public API

    print(f"done: {total} historical points stored in {cfg.db_path}")


if __name__ == "__main__":
    main()
