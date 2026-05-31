#!/usr/bin/env python3
"""
prioritize.py — the gate + rank + two-track routing for discovered gaps.

Turns a list of diagnosed candidates into two independently-budgeted, ranked
action lists (see ../../CLAUDE.md §7):

  - INTEGRITY track : structural gaps (dedup/mistyping). Low-effort, homogeneous.
                      Batch the top-N into ONE "merge duplicate entities" wave.
  - GROWTH track    : coverage/depth/freshness. Heterogeneous ingestion.
                      Top items typically collapse into a hot THEME wave.

Why two tracks: in a single shared budget, structural-dedup eats every slot
(proven 2026-05-30 — 5 of 6) and starves growth. Routing fixes that.

Inputs per candidate: name, relevance (0-1, analyst judgment), anchors (set of
strategic-anchor tags it matches), velocity (claim mentions today), gaps (from
gap_diagnostic.diagnose). Relevance + anchors are HUMAN judgment — the system
proposes, you approve.

Usage:
    python prioritize.py            # runs the 2026-05-30 demo set
    # or import: from prioritize import route
"""
from __future__ import annotations

# ---- this cycle's config (you set these) -------------------------------------
STRATEGIC_ANCHORS = {"frontier labs", "ai agents", "compute & chips"}
RELEVANCE_FLOOR = 0.4      # below this -> discard, never recorded
INTEGRITY_CAP = 5          # dedups actioned per cycle (batched into 1 wave)
GROWTH_CAP = 5             # growth gaps actioned per cycle

# scoring weights (growth track)
W_TREND, W_GAPVAL, W_ANCHOR = 0.45, 0.30, 0.25
GAP_VALUE = {"COVERAGE": 1.0, "STRUCTURAL": 0.9, "FRESHNESS": 0.6, "DEPTH": 0.5}
GAP_EFFORT = {"COVERAGE": 3, "STRUCTURAL": 1, "FRESHNESS": 2, "DEPTH": 2}


def integrity_score(relevance: float, velocity: float, vmax: float) -> float:
    # dedup value scales with the entity's traffic/importance
    return relevance * (0.6 * (velocity / vmax) + 0.4) * 100


def growth_score(relevance: float, velocity: float, vmax: float, gaps: list, anchors: set) -> float:
    gv = max((GAP_VALUE[g] for g in gaps if g in GAP_VALUE), default=0.0)
    anchor = 1.0 if anchors & STRATEGIC_ANCHORS else 0.0
    return relevance * (W_TREND * (velocity / vmax) + W_GAPVAL * gv + W_ANCHOR * anchor) * 100


def route(candidates: list[dict]) -> dict:
    """candidates: [{name, relevance, anchors:set, velocity:int, gaps:[...]}].
    Returns {"integrity":[...ranked], "growth":[...ranked], "dropped":[...], "clean":[...]}."""
    vmax = max((c["velocity"] for c in candidates), default=1) or 1
    integ, growth, dropped, clean = [], [], [], []
    for c in candidates:
        if c["relevance"] < RELEVANCE_FLOOR:
            dropped.append(c); continue
        gaps = c["gaps"]
        if gaps == ["clean"] or not gaps:
            clean.append(c); continue
        if "STRUCTURAL" in gaps:
            integ.append({**c, "score": integrity_score(c["relevance"], c["velocity"], vmax)})
        growth_gaps = [g for g in gaps if g in ("COVERAGE", "DEPTH", "FRESHNESS")]
        if growth_gaps:
            growth.append({**c, "score": growth_score(c["relevance"], c["velocity"], vmax, gaps, c["anchors"]),
                           "effort": min(GAP_EFFORT[g] for g in growth_gaps)})
    integ.sort(key=lambda x: -x["score"])
    growth.sort(key=lambda x: -x["score"])
    return {"integrity": integ, "growth": growth, "dropped": dropped, "clean": clean}


def render(routed: dict):
    print("=" * 70, "\n🔧 INTEGRITY TRACK (structural dedup) — batch top-N into ONE merge wave\n" + "=" * 70)
    for i, c in enumerate(routed["integrity"], 1):
        mark = "✅" if i <= INTEGRITY_CAP else "⏸"
        print(f"{i:>2} {c['name']:18}{c['score']:>6.1f}  trend={c['velocity']:<3} {mark}")
    print("\n" + "=" * 70, "\n🌱 GROWTH TRACK (coverage/depth/freshness) — theme-bundled ingestion\n" + "=" * 70)
    for i, c in enumerate(routed["growth"], 1):
        mark = "✅ ACTION" if i <= GROWTH_CAP else "⏸ defer"
        print(f"{i:>2} {c['name']:24}{c['score']:>6.1f}  trend={c['velocity']:<3} {','.join(c['gaps']):16} {mark}")
    if routed["dropped"]:
        print("\nDROPPED (below relevance floor):", ", ".join(c["name"] for c in routed["dropped"]))
    if routed["clean"]:
        print("CLEAN (no gap, no action):", ", ".join(c["name"] for c in routed["clean"]))


if __name__ == "__main__":
    # 2026-05-30 demo set (relevance/anchors = analyst judgment; gaps from gap_diagnostic).
    demo = [
        {"name": "OpenAI", "relevance": 1.0, "anchors": {"frontier labs"}, "velocity": 32, "gaps": ["STRUCTURAL"]},
        {"name": "Anthropic", "relevance": 1.0, "anchors": {"frontier labs"}, "velocity": 17, "gaps": ["STRUCTURAL"]},
        {"name": "Amazon", "relevance": 0.7, "anchors": set(), "velocity": 17, "gaps": ["STRUCTURAL"]},
        {"name": "Mistral AI", "relevance": 1.0, "anchors": {"frontier labs"}, "velocity": 15, "gaps": ["STRUCTURAL"]},
        {"name": "Mythos", "relevance": 0.9, "anchors": {"frontier labs"}, "velocity": 4, "gaps": ["COVERAGE"]},
        {"name": "XCENA", "relevance": 0.7, "anchors": {"compute & chips"}, "velocity": 14, "gaps": ["COVERAGE"]},
        {"name": "SK Hynix", "relevance": 0.75, "anchors": {"compute & chips"}, "velocity": 9, "gaps": ["COVERAGE"]},
        {"name": "Claude Opus 4.8", "relevance": 1.0, "anchors": {"frontier labs"}, "velocity": 6, "gaps": ["DEPTH"]},
        {"name": "OpenRouter", "relevance": 0.9, "anchors": {"ai agents"}, "velocity": 9, "gaps": ["DEPTH"]},
        {"name": "Robinhood", "relevance": 0.3, "anchors": set(), "velocity": 19, "gaps": ["COVERAGE"]},
        {"name": "Nvidia", "relevance": 0.9, "anchors": {"compute & chips"}, "velocity": 23, "gaps": ["clean"]},
    ]
    render(route(demo))
