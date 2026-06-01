#!/usr/bin/env python3
"""
gap_diagnostic.py — the hardened multi-gap diagnostic for the AI space.

Given a candidate name, resolves it ROBUSTLY (exact-name, never substring) and
runs all five gap checks. Existence != no gap: an entity that exists can still be
thin (depth), stale (freshness), or mistyped/duplicated (structural).

This is the linchpin of the discovery engine (see ../../CLAUDE.md §6). Naive
substring search produces garbage in both directions — it buries popular names
(OpenAI has 800+ substring matches) AND over-narrow type filters miss broad
geo-root types. Exact-name (`isInsensitive`) + full-type resolution is the fix.

Usage:
    python gap_diagnostic.py "OpenAI" "XCENA" "Claude Opus 4.8"
    # or import: from gap_diagnostic import diagnose

No auth needed (read-only). Endpoint is Geo testnet.
"""
from __future__ import annotations
import json, sys, time, urllib.request, urllib.error

ENDPOINT = "https://testnet-api.geobrowser.io/graphql"
AI_SPACE = "41e851610e13a19441c4d980f2f2ce6b"

# Entities that count as a real "identity" for a candidate (not assertion/media noise).
IDENTITY = {"Project", "Company", "Lab", "Provider", "Organization", "Person", "Model",
            "Model family", "Agent", "Tool", "Dataset", "Benchmark", "Topic",
            "Computing hardware", "Hardware device"}
# Types that legitimately share a name but are NOT the entity (noise that buries search).
NOISE = {"Claim", "Article", "Quote", "Data block", "Image", "Tweet", "Post",
         "News story", "News event", "Evaluation"}

# Thresholds (tune against real runs — see CLAUDE.md §14.7).
DEPTH_MIN = 5      # meaningful relations below this = depth gap
STALE_DAYS = 30    # entity untouched longer than this + trending = freshness gap
TREND_FLOOR = 5    # claim mentions at/above this = "trending now" (freshness check)
TREND_TAG_FLOOR = 15  # velocity at/above this adds the secondary "TRENDING" gap tag


def gql(query: str, retries: int = 3, backoff: float = 1.5) -> dict:
    body = json.dumps({"query": query}).encode()
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(
                ENDPOINT, data=body,
                headers={"Content-Type": "application/json", "Accept-Encoding": "identity"})
            with urllib.request.urlopen(req, timeout=30) as r:
                payload = json.loads(r.read().decode())
            if "errors" in payload:
                raise RuntimeError(payload["errors"])
            return payload.get("data", {})
        except (urllib.error.URLError, TimeoutError, urllib.error.HTTPError) as e:
            last = e
            if i < retries - 1:
                time.sleep(backoff ** i)
    raise RuntimeError(f"GraphQL failed after {retries}: {last}")


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def exact_entities(name: str, space_id: str = AI_SPACE) -> list[dict]:
    """ALL entities in the space whose name == `name` (case-insensitive). No burial.
    Returns nodes with types, timestamps, values, relation-type list."""
    q = (f'{{ entitiesConnection(spaceId:"{space_id}", first:100, '
         f'filter:{{name:{{isInsensitive:"{_esc(name)}"}}}}) '
         f'{{ nodes {{ id name updatedAt types {{ name }} '
         f'values(first:60){{ nodes {{ property {{ name }} text }} }} '
         f'relations(first:200){{ nodes {{ type {{ name }} }} }} }} }} }}')
    return (gql(q).get("entitiesConnection") or {}).get("nodes") or []


def _meaningful_rels(e: dict) -> int:
    skip = {"Types", "Cover", "Avatar", "Blocks"}
    return len([r for r in (e.get("relations") or {}).get("nodes") or []
                if (r.get("type") or {}).get("name") not in skip])


def diagnose(name: str, space_id: str = AI_SPACE, velocity: int = 0) -> dict:
    """Run all five gap checks on a candidate. Returns:
    {candidate, gaps[], canonical, all_named[], detail{}}.  gaps can be multiple."""
    ents = exact_entities(name, space_id)
    ident = [e for e in ents if any(t["name"] in IDENTITY for t in (e.get("types") or []))]
    all_named = [f"{e['name']}[{','.join(t['name'] for t in (e.get('types') or []))}]" for e in ents]

    if not ident:
        gaps = ["COVERAGE"]
        if velocity >= TREND_TAG_FLOOR:
            gaps.append("TRENDING")
        return {"candidate": name, "gaps": gaps, "canonical": None,
                "all_named": all_named,
                "detail": {"coverage": f"{len(ents)} same-name entities, none identity-typed"}}

    best = max(ident, key=_meaningful_rels)
    br = _meaningful_rels(best)
    types = [t["name"] for t in (best.get("types") or [])]
    gaps, detail = [], {"canonical": f"{best['name']} [{','.join(types)}] {br} rels", "id": best["id"]}

    # STRUCTURAL — (a) >1 same-name identity entity (dedup/merge), OR
    #             (b) a type attached more than once to ONE entity ([Lab,Lab]) — §6 STEP 2.
    dup_types = sorted({t for t in types if types.count(t) > 1})
    if len(ident) > 1 or dup_types:
        gaps.append("STRUCTURAL")
        if len(ident) > 1:
            detail["structural"] = "multiple same-name identity entities: " + " | ".join(all_named)
        if dup_types:
            detail["structural_duptype"] = f"duplicated type(s) on one entity: {dup_types} ({best['name']} [{','.join(types)}])"

    # DEPTH — thin, or missing Description / Avatar
    vals = {(v.get("property") or {}).get("name") for v in (best.get("values") or {}).get("nodes") or []}
    rels = {(r.get("type") or {}).get("name") for r in (best.get("relations") or {}).get("nodes") or []}
    miss = []
    if "Description" not in vals:
        miss.append("Description")
    if "Avatar" not in rels and any(t in ("Project", "Company", "Lab", "Provider", "Person", "Organization") for t in types):
        miss.append("Avatar")
    if br < DEPTH_MIN or miss:
        gaps.append("DEPTH")
        detail["depth"] = f"{br} rels" + (f"; missing {miss}" if miss else "")

    # FRESHNESS — trending now but content stale (WEAK: updatedAt is bumped by any edit)
    try:
        from datetime import datetime, timezone
        upd = datetime.fromtimestamp(int(best.get("updatedAt")), tz=timezone.utc)
        age = (datetime.now(timezone.utc) - upd).days
        detail["age_days"] = age
        if velocity >= TREND_FLOOR and age > STALE_DAYS:
            gaps.append("FRESHNESS")
            detail["freshness"] = f"trending ({velocity}) but untouched {age}d"
    except Exception:
        pass

    # TRENDING — secondary multi-value tag: a real gap that's also hot right now.
    # (Not a standalone gap; only tags candidates that already have a gap.)
    if gaps and velocity >= TREND_TAG_FLOOR:
        gaps.append("TRENDING")
        detail["trending"] = f"velocity {velocity} >= {TREND_TAG_FLOOR}"

    return {"candidate": name, "gaps": gaps or ["clean"], "canonical": best,
            "all_named": all_named, "detail": detail}


if __name__ == "__main__":
    names = sys.argv[1:] or ["OpenAI", "XCENA", "Claude Opus 4.8"]
    for nm in names:
        d = diagnose(nm)
        print(f"\n{nm}: {','.join(d['gaps'])}")
        for k, v in d["detail"].items():
            print(f"    {k}: {v}")
