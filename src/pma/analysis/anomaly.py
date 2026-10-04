"""Step 3: anomaly detection on probability and volume series.

Three transparent, rule-based detectors (deliberately simple and explainable):

1. prob jump      - |delta| between consecutive observations >= threshold
                    (rolling z-score reported as context when available)
2. volume spike   - 24h volume rises >= ratio x its rolling baseline and the
                    absolute increase exceeds a floor
3. divergence     - the same event priced on both platforms differs by more
                    than the threshold (markets matched by question-text
                    similarity)

All thresholds live in pma.config.Config.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence, Set, Tuple

from pma.models import MarketSnapshot

STOPWORDS: Set[str] = {
    "will", "the", "of", "in", "on", "by", "a", "an", "to", "for", "at",
    "be", "is", "are", "does", "do", "did", "before", "during", "after",
    "and", "or", "vs", "new",
}


def tokenize(text: str) -> Set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if w not in STOPWORDS and len(w) > 1}


def jaccard(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def match_markets(left: List[MarketSnapshot], right: List[MarketSnapshot],
                  threshold: float = 0.55) -> List[Tuple[MarketSnapshot, MarketSnapshot, float]]:
    """Greedy cross-platform matching by question-text similarity.

    Markets are matched pairwise (each platform market matched at most once);
    pairs below `threshold` Jaccard similarity are ignored. This is
    intentionally conservative: precision over recall.
    """
    matches: List[Tuple[MarketSnapshot, MarketSnapshot, float]] = []
    used_right: Set[str] = set()
    for l in left:
        lt = tokenize(l.question)
        best: Optional[MarketSnapshot] = None
        best_score = threshold
        for r in right:
            if r.market_id in used_right:
                continue
            score = jaccard(lt, tokenize(r.question))
            if score >= best_score:
                best, best_score = r, score
        if best is not None:
            used_right.add(best.market_id)
            matches.append((l, best, best_score))
    return matches


def detect_prob_jumps(history: Sequence[Tuple[str, float]],
                      threshold: float = 0.05) -> List[Dict]:
    """Flag consecutive-point moves of |delta| >= threshold (prob units)."""
    events: List[Dict] = []
    deltas = [p1 - p0 for (_, p0), (_, p1) in zip(history, history[1:])]
    for i, delta in enumerate(deltas):
        if abs(delta) < threshold:
            continue
        # rolling z-score of past deltas as context (needs >= 5 points)
        past = deltas[max(0, i - 20):i]
        zscore = None
        if len(past) >= 5:
            mean = sum(past) / len(past)
            var = sum((d - mean) ** 2 for d in past) / len(past)
            std = var ** 0.5
            if std > 1e-9:
                zscore = round((delta - mean) / std, 2)
        events.append({
            "ts": history[i + 1][0],
            "from": round(history[i][1], 4),
            "to": round(history[i + 1][1], 4),
            "delta": round(delta, 4),
            "zscore": zscore,
        })
    return events


def detect_volume_spikes(history: Sequence[Tuple[str, float]],
                         ratio: float = 1.5,
                         min_abs: float = 5000.0,
                         k: int = 7) -> List[Dict]:
    """Flag points where volume_24h >= ratio x rolling baseline of the
    previous k points AND the absolute increase >= min_abs (USD)."""
    events: List[Dict] = []
    vals = [v for _, v in history]
    for i in range(1, len(vals)):
        past = vals[max(0, i - k):i]
        if len(past) < 3:
            continue
        baseline = sum(past) / len(past)
        delta = vals[i] - baseline
        if baseline > 0 and delta >= min_abs and vals[i] >= baseline * ratio:
            events.append({
                "ts": history[i][0],
                "volume_24h": round(vals[i], 2),
                "baseline": round(baseline, 2),
                "delta": round(delta, 2),
            })
    return events
