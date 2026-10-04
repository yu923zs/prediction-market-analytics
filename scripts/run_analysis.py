"""Run the full analysis pipeline and write artifacts to outputs/.

    python scripts/run_analysis.py
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pma.config import Config        # noqa: E402
from pma.pipeline import run_analysis  # noqa: E402


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    result = run_analysis(Config())
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
