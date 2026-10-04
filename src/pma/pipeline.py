"""Pipeline orchestration: snapshot ingestion and the analysis report."""
from __future__ import annotations

import csv
import json
import logging
from typing import Dict, List

from pma.analysis.anomaly import (detect_prob_jumps, detect_volume_spikes,
                                  match_markets)
from pma.analysis.screening import select_top_markets
from pma.analysis.tracking import parse_ts, summarize_market
from pma.agent import run_agent
from pma.config import Config
from pma.connectors import KalshiConnector, PolymarketConnector
from pma.connectors.base import AuthRequiredError, BaseConnector
from pma.models import MarketSnapshot
from pma.storage import Store

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- ingestion

def _connectors(cfg: Config) -> List[BaseConnector]:
    return [
        PolymarketConnector(timeout=cfg.request_timeout,
                            pages=cfg.polymarket_pages,
                            page_size=cfg.page_size),
        KalshiConnector(timeout=cfg.request_timeout),
    ]


def run_snapshot(cfg: Config) -> Dict[str, object]:
    """One ingestion cycle: fetch both platforms, persist unified snapshots."""
    status: Dict[str, object] = {}
    with Store(cfg.db_path) as store:
        for connector in _connectors(cfg):
            try:
                snaps = connector.fetch_markets(cfg.top_n_markets)
                n = store.upsert(snaps)
                status[connector.platform] = {"markets": len(snaps), "upserted": n}
                log.info("%s: %d markets stored", connector.platform, len(snaps))
            except AuthRequiredError as e:
                status[connector.platform] = {"skipped": str(e)}
                log.warning("%s", e)
            except Exception as e:  # noqa: BLE001 - one platform must not kill the other
                status[connector.platform] = {"error": str(e)}
                log.error("%s ingestion failed: %s", connector.platform, e)
    return status


# ----------------------------------------------------------------- analysis

def _signal(kind: str, s: MarketSnapshot, ev: Dict,
            severity: float) -> Dict:
    return {
        "type": kind,
        "platform": s.platform,
        "market_id": s.market_id,
        "question": s.question,
        "ts": ev.get("ts"),
        "severity": round(severity, 4),
        "detail": ev,
    }


def _collect_signals(store: Store, selected: List[MarketSnapshot],
                     cfg: Config):
    signals: List[Dict] = []
    market_infos: List[Dict] = []

    for s in selected:
        prob_hist = store.history(s.platform, s.market_id, "prob")
        vol_hist = store.history(s.platform, s.market_id, "volume_24h")
        summary = summarize_market(prob_hist, cfg.change_window_minutes)
        market_infos.append({
            "platform": s.platform,
            "market_id": s.market_id,
            "question": s.question,
            "volume_24h": s.volume_24h,
            **summary,
        })
        for ev in detect_prob_jumps(prob_hist, cfg.jump_threshold):
            signals.append(_signal("prob_jump", s, ev, abs(ev["delta"])))
        for ev in detect_volume_spikes(vol_hist, cfg.volume_spike_ratio,
                                       cfg.volume_spike_min_abs):
            signals.append(_signal("volume_spike", s, ev,
                                   ev["delta"] / ev["baseline"]))

    # cross-platform divergence on the same event
    pm = [s for s in selected if s.platform == "polymarket"]
    ks = [s for s in selected if s.platform == "kalshi"]
    for l, r, score in match_markets(pm, ks, cfg.match_jaccard):
        if l.prob is None or r.prob is None:
            continue
        diff = l.prob - r.prob
        if abs(diff) >= cfg.divergence_threshold:
            detail = {"polymarket_prob": l.prob, "kalshi_prob": r.prob,
                      "diff": round(diff, 4), "match_score": round(score, 3)}
            signals.append(_signal("divergence", l, detail, abs(diff)))

    signals.sort(key=lambda x: x["severity"], reverse=True)
    return signals, market_infos


def _write_csv(path, snaps: List[MarketSnapshot]):
    fields = list(MarketSnapshot.KEY_FIELDS)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for s in snaps:
            writer.writerow(s.to_dict())


def _plot_prob_history(store: Store, selected: List[MarketSnapshot], path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    series = []
    for s in selected:
        hist = store.history(s.platform, s.market_id, "prob")
        if len(hist) >= 5:
            series.append((s, hist))
    series.sort(key=lambda t: t[0].volume_24h or 0.0, reverse=True)
    series = series[:6]
    if not series:
        return None

    fig, ax = plt.subplots(figsize=(10, 6))
    for s, hist in series:
        xs = [parse_ts(ts) for ts, _ in hist]
        ys = [p for _, p in hist]
        q = s.question if len(s.question) <= 42 else s.question[:42] + "..."
        ax.plot(xs, ys, linewidth=1.5, label=f"[{s.platform}] {q}")
    ax.set_title("Implied probability history - watched markets")
    ax.set_xlabel("time (UTC)")
    ax.set_ylabel("implied YES probability")
    ax.set_ylim(0, 1)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, loc="best")
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path


def run_analysis(cfg: Config) -> Dict[str, object]:
    """Screening -> tracking -> anomaly detection -> agent report -> outputs."""
    cfg.outputs_dir.mkdir(parents=True, exist_ok=True)
    with Store(cfg.db_path) as store:
        latest = store.latest_snapshots()
        if not latest:
            raise SystemExit("no snapshots stored yet - run scripts/snapshot_loop.py first")

        selected: List[MarketSnapshot] = []
        for platform in ("polymarket", "kalshi"):
            plat = [s for s in latest if s.platform == platform]
            selected.extend(select_top_markets(
                plat, cfg.min_volume_24h_usd, cfg.top_n_markets))

        signals, market_infos = _collect_signals(store, selected, cfg)

        # ---- outputs ----
        signals_path = cfg.outputs_dir / "signals.json"
        signals_path.write_text(json.dumps({
            "n_markets_tracked": len(selected),
            "n_signals": len(signals),
            "signals": signals,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        csv_path = cfg.outputs_dir / "snapshots_sample.csv"
        _write_csv(csv_path, latest)

        agent_report = run_agent(signals, market_infos, cfg)
        report_path = cfg.outputs_dir / "agent_report.json"
        report_path.write_text(json.dumps(agent_report, ensure_ascii=False,
                                          indent=2), encoding="utf-8")

        chart_path = _plot_prob_history(store, selected,
                                        cfg.outputs_dir / "prob_history.png")

    return {
        "n_markets_tracked": len(selected),
        "n_signals": len(signals),
        "signals": str(signals_path),
        "agent_report": str(report_path),
        "snapshots_csv": str(csv_path),
        "chart": str(chart_path) if chart_path else None,
    }
