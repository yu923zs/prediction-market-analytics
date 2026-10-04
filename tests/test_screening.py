from pma.analysis.screening import select_top_markets
from pma.analysis.tracking import summarize_market
from pma.models import MarketSnapshot


def _snap(market_id, question, prob, volume_24h, platform="polymarket"):
    return MarketSnapshot(ts="2026-10-04T08:00:00Z", platform=platform,
                          market_id=market_id, question=question, prob=prob,
                          volume_24h=volume_24h)


class TestScreening:
    def test_filters_and_ranks(self):
        snaps = [
            _snap("1", "a", 0.5, 50_000),
            _snap("2", "b", 0.6, 500),      # below floor -> dropped
            _snap("3", "c", 0.7, 120_000),
            _snap("4", "d", 0.4, 10_000),
        ]
        top = select_top_markets(snaps, min_volume_24h_usd=10_000, top_n=2)
        assert [s.market_id for s in top] == ["3", "1"]

    def test_caps_top_n(self):
        snaps = [_snap(str(i), "q", 0.5, 100_000 + i) for i in range(10)]
        assert len(select_top_markets(snaps, 10_000, 3)) == 3

    def test_missing_volume_dropped(self):
        snaps = [_snap("1", "q", 0.5, None)]
        assert select_top_markets(snaps, 10_000, 5) == []


class TestTracking:
    def test_summarize_windows(self):
        hist = [("2026-10-03T08:00:00Z", 0.40),
                ("2026-10-03T20:00:00Z", 0.45),
                ("2026-10-04T08:00:00Z", 0.55)]
        s = summarize_market(hist)
        assert s["n_points"] == 3
        assert s["prob_now"] == 0.55
        # 24h baseline: the point exactly 24h earlier (0.40)
        assert abs(s["change_24h"] - 0.15) < 1e-9
        # 1h baseline: the most recent point at/after the cutoff, i.e. 12h ago (0.45)
        assert abs(s["change_1h"] - 0.10) < 1e-9
        assert s["span_hours"] == 24.0

    def test_baseline_falls_back_when_window_not_covered(self):
        hist = [("2026-10-04T07:30:00Z", 0.40),
                ("2026-10-04T07:45:00Z", 0.42),
                ("2026-10-04T08:00:00Z", 0.44)]
        s = summarize_market(hist, window_minutes=60)
        # every point is inside the 1h window -> earliest available point
        assert abs(s["change_1h"] - 0.04) < 1e-9

    def test_empty_history(self):
        assert summarize_market([]) == {"n_points": 0}
