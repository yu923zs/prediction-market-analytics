"""Step 2: track how implied probabilities move over time."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple


def parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _change_over_window(history: List[Tuple[str, float]],
                        window_minutes: int,
                        now: datetime) -> Optional[float]:
    """prob_now - prob at the start of the trailing window.

    If stored history does not yet span the window, the earliest available
    point is used as the baseline (and the caller can check span_hours).
    """
    if len(history) < 2:
        return None
    cutoff = now - timedelta(minutes=window_minutes)
    baseline = None
    for ts, value in history:
        if parse_ts(ts) <= cutoff:
            baseline = value
        else:
            break
    if baseline is None:
        baseline = history[0][1]
    return history[-1][1] - baseline


def summarize_market(history: List[Tuple[str, float]],
                     window_minutes: int = 60) -> Dict:
    """Summary of a (ts, prob) series for reporting / agent context."""
    if not history:
        return {"n_points": 0}
    now = parse_ts(history[-1][0])
    span_hours = (now - parse_ts(history[0][0])).total_seconds() / 3600.0
    return {
        "n_points": len(history),
        "prob_now": history[-1][1],
        "prob_first": history[0][1],
        "change_1h": _change_over_window(history, min(window_minutes, 60), now),
        "change_24h": _change_over_window(history, 24 * 60, now),
        "span_hours": round(span_hours, 2),
    }
