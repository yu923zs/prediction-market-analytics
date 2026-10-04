"""Agent layer: turn structured signals into a structured analyst view.

Two engines with the same output contract:
- "llm:<model>" - an OpenAI-compatible chat endpoint (default DeepSeek) fed a
  compact JSON context, returning strict JSON.
- "rules"       - deterministic fallback when no API key is configured or the
  LLM call fails, so the pipeline always produces a report.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List

import requests

from pma.config import Config

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a senior prediction-market analyst.
You receive JSON describing prediction markets (Polymarket / Kalshi), their
implied probabilities, recent probability moves, volume, and anomaly signals
(prob jumps, volume spikes, cross-platform divergence).
Interpret the signals like a trading desk analyst: what likely happened,
how credible the signal is, and what a watcher should do next.
Respond with STRICT JSON only, no markdown fences, matching this schema:
{
  "summary": "2-3 sentence overall market read",
  "markets": [
    {
      "platform": "...",
      "market_id": "...",
      "question": "...",
      "signals": ["..."],
      "interpretation": "1-3 sentences",
      "confidence": "high|medium|low",
      "suggested_action": "watch|investigate|avoid"
    }
  ]
}
Only include markets that were passed in. Do not invent markets or numbers."""


def build_context(signals: List[Dict], market_infos: List[Dict]) -> Dict[str, Any]:
    return {
        "generated_at": utc_now_iso(),
        "n_signals": len(signals),
        "signals": signals,
        "markets": market_infos,
    }


def run_agent(signals: List[Dict], market_infos: List[Dict],
              config: Config) -> Dict[str, Any]:
    context = build_context(signals, market_infos)
    if config.llm_api_key:
        try:
            report = _call_llm(config, context)
            report["engine"] = f"llm:{config.llm_model}"
            report["generated_at"] = context["generated_at"]
            return report
        except Exception as e:  # noqa: BLE001 - degrade gracefully by design
            log.warning("LLM call failed (%s); falling back to rules", e)
    else:
        log.info("no LLM API key configured; using rule-based analyst")
    report = _rule_based(signals, market_infos)
    report["generated_at"] = context["generated_at"]
    return report


def _call_llm(config: Config, context: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{config.llm_base_url.rstrip('/')}/chat/completions"
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {config.llm_api_key}"},
        json={
            "model": config.llm_model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",
                 "content": json.dumps(context, ensure_ascii=False)},
            ],
            "temperature": 0.2,
        },
        timeout=config.llm_timeout,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    return _extract_json(content)


def _extract_json(text: str) -> Dict[str, Any]:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in LLM response")
    return json.loads(text[start:end + 1])


def _rule_based(signals: List[Dict], market_infos: List[Dict]) -> Dict[str, Any]:
    by_market: Dict[str, List[Dict]] = {}
    for s in signals:
        key = f"{s['platform']}:{s['market_id']}"
        by_market.setdefault(key, []).append(s)

    markets = []
    for info in market_infos:
        key = f"{info['platform']}:{info['market_id']}"
        m_signals = by_market.get(key, [])
        if not m_signals:
            continue
        types = {s["type"] for s in m_signals}
        if {"prob_jump", "volume_spike"} <= types:
            action = "investigate"
        elif types:
            action = "watch"
        else:
            action = "watch"
        detail = "; ".join(
            f"{s['type']} ({json.dumps(s['detail'], ensure_ascii=False)})"
            for s in m_signals)
        markets.append({
            "platform": info["platform"],
            "market_id": info["market_id"],
            "question": info["question"],
            "signals": sorted(types),
            "interpretation": (
                f"Tracked signals: {detail}. Prob now "
                f"{info.get('prob_now')}, 1h change {info.get('change_1h')}. "
                f"Rule-based view: review the underlying news before acting."),
            "confidence": "medium",
            "suggested_action": action,
        })

    return {
        "engine": "rules",
        "summary": (
            f"{len(market_infos)} markets tracked, {len(signals)} signals "
            f"raised across {len(markets)} markets."),
        "markets": markets,
    }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
