#!/usr/bin/env python3
"""
theme_gaps.py — theme-level gap diagnostic (Stage 5b).

Takes the themes from theme_heat and, for each hot theme, resolves whether the target
space has a developed Topic for it — emitting a theme-level gap (Coverage / Structural /
Depth at Topic altitude). These become theme Gap findings (structuring work: create /
attach / develop a topic page), distinct from entity discoveries.

Resolution is EXACT-name + Topic-type-filtered (NOT broad substring — that times out on
common theme names). Same exact-name discipline as the entity diagnostic.

Usage:
    python theme_gaps.py --in harvest.json --space <space_id> [--min-heat 2]
"""
from __future__ import annotations
import argparse, json
from collections import Counter
from gap_diagnostic import gql, _esc   # reuse the client
from theme_heat import themes          # reuse the clustering

TOPIC_TYPE = "5ef5a5860f274d8e8f6c59ae5b3e89e2"  # geo-root Topic


def diagnose_theme(name, space_id):
    """Return (gap, detail). gap in {COVERAGE, STRUCTURAL, DEPTH, None}."""
    q = (f'{{ entitiesConnection(typeId:"{TOPIC_TYPE}", first:10, '
         f'filter:{{name:{{isInsensitive:"{_esc(name)}"}}}}) '
         f'{{ nodes {{ id name spaceIds }} }} }}')
    try:
        topics = (gql(q).get("entitiesConnection") or {}).get("nodes") or []
    except Exception:
        return None, "query error"
    if not topics:
        return "COVERAGE", "no Topic exists anywhere — create it in the space"
    in_space = [t for t in topics if space_id in (t.get("spaceIds") or [])]
    if not in_space:
        where = (topics[0].get("spaceIds") or ["?"])[0][:8]
        return "STRUCTURAL", f"Topic exists but not in the target space (in {where}…) — attach + develop here"
    # structured?
    eid = in_space[0]["id"]
    try:
        r = (gql(f'{{ entity(id:"{eid}"){{ relations(first:120){{ nodes {{ type {{ name }} }} }} }} }}') or {}).get("entity") or {}
        rc = Counter((x.get("type") or {}).get("name") for x in (r.get("relations") or {}).get("nodes") or [])
    except Exception:
        return None, "structure check error"
    members = rc.get("Related entities", 0) + rc.get("Related projects", 0) + rc.get("Related people", 0)
    page = "Blocks" in rc or "Tabs" in rc
    if members < 3 and not page:
        return "DEPTH", f"Topic exists in-space but thin (subtopics={rc.get('Subtopics',0)} members={members} page=no) — develop it"
    return None, f"Topic developed (subtopics={rc.get('Subtopics',0)} members={members} page={page})"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="harvest.json")
    ap.add_argument("--space", required=True)
    ap.add_argument("--min-heat", type=int, default=2)
    a = ap.parse_args()
    docs = json.load(open(a.inp))
    rows = [r for r in themes(docs) if (r["news"] + r["pod"]) >= a.min_heat]
    print(f"{'theme':40}{'heat':>5}  theme-gap -> action")
    print("-" * 90)
    for r in rows:
        gap, detail = diagnose_theme(r["theme"], a.space)
        tag = f"{gap}(theme)" if gap else "—ok—"
        print(f"{r['theme'][:40]:40}{r['news']+r['pod']:>5}  {tag}: {detail}")
