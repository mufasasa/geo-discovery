#!/usr/bin/env python3
"""
run.py — the discovery driver. Chains the mechanical stages so the firing agent runs
commands instead of authoring glue each run (the #1 friction in the first live run).

Subcommands:
  profile  --space <id>
      Print the auto-derived space profile (identity types + datasets target) so the
      operator can eyeball the config before running. No writes.

  harvest  --space <id> [--days 2] [--with-episodes] [--out harvest.json]
      Stage 1 + the profile banner. Episodes are filtered by topic-overlap (no allowlist).

  diagnose --space <id> --candidates candidates.json [--out profiles.json]
      Stages 2→3: for each candidate {name, velocity} run the 5-gap diagnostic, PRINTING
      PROGRESS as it goes (no more polling a background job), and emit one profile per
      candidate with the resolved canonical/duplicate IDs already filled in — so Stage 6
      writes merge/create actions without re-resolving entities.

NER (Stage 2) stays the agent's LLM step: read harvest.json → write candidates.json.
Stage 4 (route) and Stage 5 (theme_heat/theme_gaps) remain their own scripts.
"""
from __future__ import annotations
import argparse, json, sys, time

from space_profile import profile as space_profile
from gap_diagnostic import diagnose
import harvest as H


def _banner(space_id):
    p = space_profile(space_id)
    print(f"── space {space_id}")
    print(f"   datasets target : {p['datasets_space'] or '(unmapped — set in space_profile.DATASETS_SPACE)'}")
    print(f"   identity types  ({len(p['identity_type_names'])}): {', '.join(p['identity_type_names'])}")
    return p


def cmd_profile(a):
    _banner(a.space)


def cmd_harvest(a):
    _banner(a.space)
    docs = H.harvest(a.space, a.days, a.with_episodes, a.min_topic_overlap)
    json.dump(docs, open(a.out, "w"), indent=1)
    nnews = sum(1 for d in docs if d["kind"] == "news")
    neps = sum(1 for d in docs if d["kind"] == "episode")
    nclaims = sum(len(d.get("claims") or []) for d in docs)
    shows = sorted({d.get("podcast") for d in docs if d["kind"] == "episode" and d.get("podcast")})
    print(f"\nharvested {nnews} news + {neps} episodes ({nclaims} claims) -> {a.out}")
    if shows:
        print(f"on-domain shows (by topic overlap): {', '.join(shows)}")


def _load_candidates(path):
    raw = json.load(open(path))
    out = []
    for c in raw:
        if isinstance(c, str):
            out.append({"name": c, "velocity": 0})
        else:
            out.append({"name": c.get("name") or c.get("candidate"),
                        "velocity": int(c.get("velocity") or 0)})
    return [c for c in out if c["name"]]


def cmd_diagnose(a):
    _banner(a.space)
    cands = _load_candidates(a.candidates)
    n = len(cands)
    print(f"\ndiagnosing {n} candidates…")
    profiles, t0 = [], time.time()
    for i, c in enumerate(cands, 1):
        try:
            d = diagnose(c["name"], a.space, velocity=c["velocity"])
        except Exception as e:
            d = {"candidate": c["name"], "gaps": ["ERROR"], "detail": {"error": str(e)[:200]}}
        det = d.get("detail") or {}
        profiles.append({
            "candidate": d.get("candidate"), "velocity": c["velocity"],
            "gaps": d.get("gaps"),
            "canonical_id": det.get("canonical_id") or det.get("id"),
            "dup_ids": det.get("dup_ids"), "related_id": det.get("related_id"),
            "detail": det,
        })
        print(f"  [{i:>3}/{n}] {c['name']:32.32} → {','.join(d.get('gaps') or [])}")
    json.dump(profiles, open(a.out, "w"), indent=1)
    from collections import Counter
    tally = Counter(g for p in profiles for g in (p["gaps"] or []))
    print(f"\ndone in {int(time.time()-t0)}s -> {a.out}")
    print("gap tally:", dict(tally))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("profile"); sp.add_argument("--space", required=True); sp.set_defaults(fn=cmd_profile)
    sh = sub.add_parser("harvest")
    sh.add_argument("--space", required=True); sh.add_argument("--days", type=int, default=2)
    sh.add_argument("--with-episodes", action="store_true")
    sh.add_argument("--min-topic-overlap", type=int, default=H.MIN_TOPIC_OVERLAP)
    sh.add_argument("--out", default="harvest.json"); sh.set_defaults(fn=cmd_harvest)
    dg = sub.add_parser("diagnose")
    dg.add_argument("--space", required=True); dg.add_argument("--candidates", required=True)
    dg.add_argument("--out", default="profiles.json"); dg.set_defaults(fn=cmd_diagnose)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
