---
name: geo-discovery
description: >
  Run an independent gap-discovery pass over a Geo space's daily content stream and
  publish the gaps as Gap finding entities. Surfaces coverage, depth, freshness,
  structural, and trending gaps at both entity and theme altitude. Triggers on
  "run discovery", "discover gaps", "what's missing in <space>", "discovery pass".
version: latest
authors: CptMoh
tools: Claude Code
---

# geo-discovery

Self-contained discovery engine for the Geo knowledge graph. Mines the daily content
stream a space already ingests (News stories + topic-matched podcast episodes + their
Claims), finds the five gap types, ranks them, and produces Gap finding entities for review.

**Self-configuring per space.** Identity types, on-domain podcasts, and the publish
target are AUTO-DERIVED from the target space at run time (`scripts/space_profile.py`),
so the same skill runs on AI / crypto / health / any space with no per-space tuning. The
only hand-maintained knob is the global content/taxonomy denylist in `space_profile.py`.

**Stateless by design.** Every run is independent — it must NOT read prior-run
findings or drafted waves. Assume no previous run exists. (This is how the process
is perfected: clean-room runs you can compare.)

## When to use
The operator wants to run a discovery cycle on a space (AI, crypto, health, …) and
get a ranked list of gaps worth acting on.

## Inputs
- `space_id` (required) — the Geo space to run against (e.g. AI `41e851610e13a19441c4d980f2f2ce6b`).
- `days` (default 2) — recency window for the harvest.
- `strategic_anchors` — **OPTIONAL** bias only. Default runs need none: relevance is data-driven
  (trending + theme-fit). Pass `--anchors a,b,c` to Stage-4 routing only if you want to tilt a cycle.
- `action_capacity` (default 5 per track).

## Dependencies
- `python3` (standard library only — no pip install needed).
- Read access to the Geo GraphQL endpoint (baked into the scripts; no auth).
- For Stage 6 only: the `geo-publish` skill + the operator's signing key (write access).
- The `Gap finding` / `Gap type` / `Gap status` types must exist on Geo to publish.

## Configuration — auto-derived, not hand-tuned
Run `python3 scripts/space_profile.py <space_id>` to see what the run will use:
- **Identity types** = the space's own types minus a global content/taxonomy denylist minus
  orphan types. (AI → Model/Provider/Lab/Agent…; crypto → Project/Protocol/Token/Network/DEX…)
- **On-domain podcasts** = episodes whose Topics overlap the space's own topic vocabulary
  (no allowlist; `harvest.py` derives it).
- **Publish target** = the space's datasets space from `space_profile.DATASETS_SPACE` (add one
  line per space; reuses the shared Gap-finding ontology by ID).
New space → no config edits; only add its datasets-space mapping before Stage 6.

## Guardrails (non-negotiable)
- **Resolve exact-name first, then a normalized + type-scoped fuzzy fallback.** `gap_diagnostic`
  matches by `isInsensitive`, then normalizes (folds unicode dash-confusables like the U+2011 in
  `GPT‑5.5`) and runs a TYPE-SCOPED substring over identity types only (catches `Mythos` inside
  `Claude Mythos Preview`). NEVER a bare all-types substring — that buries popular entities
  (`OpenAI` = 1596 all-types hits) and produces false "missing" verdicts. A norm-equal hit = same
  entity (format variant, not a gap); a token/cross-type hit = related entity → keep the gap but
  set `Gap finding subject` and flag enrich-vs-create.
- **Existence ≠ no gap.** Run all five checks; an entity that exists can still be thin,
  stale, or duplicated.
- **Enrich, don't duplicate.** Before any "create", confirm the entity doesn't exist.
- **Relations over free text. Type discipline. Every fact cites Sources.**
- **Read-only except Stage 6.** Nothing writes to the graph before the review gate.
- **Never auto-publish.** Stage 6 is human-in-loop.

## Procedure (6 stages)

### Stage 1 — Harvest  ·  Automated
```
python3 scripts/run.py harvest --space <space_id> --days 2 --with-episodes --out harvest.json
```
(prints the auto-derived profile banner, then harvests). → `harvest.json`: recent News stories
(+ topic-matched podcast episodes) with their `claims[]` and `topics[]`. Episodes are kept by
topic-overlap with the space — no allowlist.

### Stage 2 — Extract candidates (NER)  ·  Automated (LLM)
Read `harvest.json`. Following `references/ner_prompt.md`, extract the distinct named
entities (orgs, labs, models, products, programs, people) referenced in the claim text
and story titles. → `candidates[]` (list of names).

### Stage 3 — Diagnose  ·  Automated
Write the Stage-2 output to `candidates.json` (`[{"name","velocity"}, …]`) and run the driver —
it diagnoses every candidate with live PROGRESS (no polling a background job) and writes
`profiles.json` with the resolved IDs already filled in:
```
python3 scripts/run.py diagnose --space <space_id> --candidates candidates.json --out profiles.json
```
Identity resolution is **auto-derived per space** (no hardcoded type list). Each profile carries
`gaps[]`, `canonical_id`, and — for structural dedup — `dup_ids[]` (the exact entities to merge),
so Stage 6 writes the merge/create action without re-resolving entities. (Importable too:
`from gap_diagnostic import diagnose`.)

### Stage 4 — Score + route  ·  Automated (no input required)
```
python3 scripts/run.py route --profiles profiles.json --harvest harvest.json
```
Ranking is **data-driven** — there is NO manual `relevance` or `strategic_anchors` to enter.
Score ≈ `trending(velocity) + gap_value + theme_fit`, where the hot themes are derived from the
harvest itself (Stage-5 cross-source signal) and `theme_fit` boosts candidates that belong to a
hot theme. (Strategic anchors presupposed what discovery is meant to surface; they're now an
OPTIONAL `--anchors a,b,c` bias, not a required input.)
→ two ranked tracks: **Integrity** (structural dedup, batch into one merge wave) and
**Growth** (coverage/depth/freshness, theme-bundled). The Stage-6 review gate is where the
operator de-selects anything off-domain — no per-candidate scoring needed.

### Stage 5 — Theme heat + theme-gap diagnosis  ·  Automated
```
python3 scripts/theme_heat.py  --in harvest.json
python3 scripts/theme_gaps.py  --in harvest.json --space <space_id>
```
`theme_heat` classifies themes CROSS-SOURCE (DEEP-eligible) / podcast-only (STANDARD) /
news-only (provisional) — cross-source agreement is the sustained-heat signal that sets
depth tier. `theme_gaps` then resolves each hot theme against the target space's Topic
taxonomy (exact-name + Topic-type filtered) and emits a **theme-level gap**:
- **Coverage(theme):** no Topic exists → create it.
- **Structural(theme):** Topic exists but not in this space (e.g. only in podcasts) → attach + develop here.
- **Depth(theme):** Topic exists in-space but thin/disconnected → develop the page.

Themes are first-class discovery output, not just a heat map: each theme gap becomes a
`Gap finding` (structuring work — build/attach/develop a topic page; feeds `page-developer`).

### Stage 6 — Publish discoveries  ·  Human-in-loop (review gate)
Draft a `Gap finding` per accepted gap — entity-level AND theme-level — following
`references/drafting-conventions.md` (human-first name/description/action) and
`references/discovery-schema.md`. Always set **Publish date**; add the `Trending` gap tag
when velocity ≥ TREND_TAG_FLOOR. Operator reviews; on approval, publish via `geo-publish`.
**Enrich-vs-create lives here** — a "coverage" gap that's a sub-thing of an existing entity
(a program inside a lab, a model from a lab) becomes an enrich/link action, not a new entity.

**Publish mechanics — follow `references/stage6-publish.md`, not the generic geo-publish doc.**
Gap findings go to a DAO space via propose+vote, and several geo-publish defaults silently fail
here: FAST does NOT auto-execute (you must cast a separate YES vote), the real `voteProposal`
signature differs from the doc, `type:"url"` is unsupported (use `text`), and dates land in the
`datetime` field. The reference has the worked target (AI datasets DAO), the exact call shapes,
and the post-publish verification gotchas.

## Output
A ranked Gap finding set (two tracks) + a theme map with depth tiers, and — on approval —
`Gap finding` entities published to the space (status `Proposed`).

## Files
- `scripts/space_profile.py` — auto-derives identity types + datasets target per space (the global denylist lives here)
- `scripts/run.py` — driver: `profile` / `harvest` / `diagnose` subcommands (progress + structured output; run this instead of authoring glue)
- `scripts/harvest.py` — Stage 1 (topic-overlap episode filter)
- `scripts/gap_diagnostic.py` — Stage 3 (5-gap diagnostic; exact-name + normalized type-scoped fuzzy fallback)
- `scripts/prioritize.py` — Stage 4 (gate + two-track rank)
- `scripts/theme_heat.py` — Stage 5 (theme clustering + cross-source classification)
- `scripts/theme_gaps.py` — Stage 5b (theme-level gap diagnosis → theme Gap findings)
- `references/ner_prompt.md` — Stage 2 extraction prompt
- `references/discovery-schema.md` — the Gap finding entity schema for Stage 6
- `references/drafting-conventions.md` — human-first naming/description/action + required props (Stage 6)
- `references/stage6-publish.md` — Stage 6 DAO publish mechanics + gotchas (propose+vote, voteProposal signature, url→text, dates)
