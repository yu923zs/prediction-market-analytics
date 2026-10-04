from pma.analysis.anomaly import (detect_prob_jumps, detect_volume_spikes,
                                  jaccard, match_markets, tokenize)
from pma.models import MarketSnapshot


def _snap(platform, market_id, question, prob):
    return MarketSnapshot(ts="2026-10-04T08:00:00Z", platform=platform,
                          market_id=market_id, question=question, prob=prob)


class TestProbJumps:
    def test_flags_large_move(self):
        hist = [("2026-10-04T07:00:00Z", 0.40),
                ("2026-10-04T07:30:00Z", 0.42),
                ("2026-10-04T08:00:00Z", 0.51)]
        events = detect_prob_jumps(hist, threshold=0.05)
        assert len(events) == 1
        assert events[0]["delta"] == 0.09
        assert events[0]["from"] == 0.42 and events[0]["to"] == 0.51

    def test_ignores_small_moves(self):
        hist = [("2026-10-04T07:00:00Z", 0.40),
                ("2026-10-04T08:00:00Z", 0.42)]
        assert detect_prob_jumps(hist, threshold=0.05) == []


class TestVolumeSpikes:
    def test_detects_spike(self):
        base = [("2026-10-04T0%d:00:00Z" % i, 10_000.0) for i in range(1, 5)]
        spike = base + [("2026-10-04T05:00:00Z", 30_000.0)]
        events = detect_volume_spikes(spike, ratio=1.5, min_abs=5_000.0)
        assert len(events) == 1
        assert events[0]["volume_24h"] == 30_000.0

    def test_ignores_small_absolute_change(self):
        hist = [("2026-10-04T0%d:00:00Z" % i, 10_000.0) for i in range(1, 5)]
        hist.append(("2026-10-04T05:00:00Z", 10_500.0))
        assert detect_volume_spikes(hist, ratio=1.5, min_abs=5_000.0) == []


class TestMatching:
    def test_jaccard(self):
        a = tokenize("Will the Fed hold rates in March?")
        b = tokenize("Fed holds rates steady in March?")
        assert jaccard(a, b) >= 0.5

    def test_matches_same_event_across_platforms(self):
        pm = [_snap("polymarket", "1", "Will the Fed hold rates in March?", 0.80)]
        ks = [_snap("kalshi", "KXFED-26MAR19-T3.75", "Fed holds rates in March?", 0.65)]
        matches = match_markets(pm, ks, threshold=0.4)
        assert len(matches) == 1
        assert matches[0][2] >= 0.4

    def test_does_not_match_unrelated(self):
        pm = [_snap("polymarket", "1", "Will Bitcoin close above $100k in 2026?", 0.4)]
        ks = [_snap("kalshi", "KXNBA", "Will the Lakers win the NBA title?", 0.2)]
        assert match_markets(pm, ks, threshold=0.55) == []
