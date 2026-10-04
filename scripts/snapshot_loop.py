"""Ingestion loop. Examples:

    python scripts/snapshot_loop.py --once          # single cycle
    python scripts/snapshot_loop.py --interval 300 --cycles 12
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pma.config import Config          # noqa: E402
from pma.pipeline import run_snapshot  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true",
                        help="run a single cycle and exit")
    parser.add_argument("--interval", type=int, default=300,
                        help="seconds between cycles (default 300)")
    parser.add_argument("--cycles", type=int, default=4,
                        help="number of cycles when looping (default 4)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    cfg = Config()

    cycles = 1 if args.once else args.cycles
    for i in range(cycles):
        status = run_snapshot(cfg)
        print(f"[cycle {i + 1}/{cycles}] {status}")
        if i < cycles - 1:
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
