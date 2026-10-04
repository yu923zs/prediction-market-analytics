"""End-to-end smoke test for the analysis pipeline.

Uses synthetic snapshots in a tmp directory (no network, no real API) to
verify screening -> tracking -> anomaly detection -> agent -> artifacts.
"""
import json
from datetime import datetime, timedelta, timezone

from pma.config import Config
from pma.models import MarketSnapshot
from pma.pipeline import run_analysis
from pma.storage import Store


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_snapshots():
    base = datetime(2026, 10, 4, 6, 0, tzinfo=timezone.utc)
    snaps = []
    # market A: calm until a 9pp jump, with a volume spike
    probs_a = [0.40, 0.41, 0.405, 0.41, 0.50]
    vols_a = [20_000, 20_500, 19_800, 21_000, 60_000]
    for i, (p, v) in enumerate(zip(probs_a, vols_a)):
        snaps.append(MarketSnapshot(
            ts=_iso(base + timedelta(minutes=30 * i)),
            platform="polymarket", market_id="A",
            question="Will the Fed hold rates in March 2026?",
            prob=p, volume_24h=float(v)))
    # market B: calm, no signal
    for i in range(5):
        snaps.append(MarketSnapshot(
            ts=_iso(base + timedelta(minutes=30 * i)),
            platform="polymarket", market_id="B",
            question="Will it rain in London on Monday?",
            prob=0.5 + i * 0.001, volume_24h=15_000.0))
    # kalshi twin of market A, priced 15pp away -> divergence
    snaps.append(MarketSnapshot(
        ts=_iso(base + timedelta(minutes=120)),
        platform="kalshi", market_id="KXFED-26MAR-T",
        question="Fed holds rates in March 2026?",
        prob=0.65, volume_24h=30_000.0))
    return snaps


def test_pipeline_end_to_end(tmp_path):
    cfg = Config()
    cfg.db_path = tmp_path / "markets.db"
    cfg.outputs_dir = tmp_path / "outputs"

    with Store(cfg.db_path) as store:
        assert store.upsert(_make_snapshots()) == 11

    result = run_analysis(cfg)
    assert result["n_markets_tracked"] >= 2

    signals = json.loads((tmp_path / "outputs" / "signals.json").read_text(encoding="utf-8"))
    kinds = {s["type"] for s in signals["signals"]}
    assert "prob_jump" in kinds       # market A 0.41 -> 0.50
    assert "volume_spike" in kinds    # market A 21k -> 60k
    assert "divergence" in kinds      # polymarket 0.50 vs kalshi 0.65

    report = json.loads((tmp_path / "outputs" / "agent_report.json").read_text(encoding="utf-8"))
    assert report["engine"] == "rules"   # no API key in test env
    assert "markets" in report and report["markets"]
    assert (tmp_path / "outputs" / "snapshots_sample.csv").exists()
    assert (tmp_path / "outputs" / "prob_history.png").exists()
