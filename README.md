# geo-discovery

Claude Code skill that runs an **independent, stateless gap-discovery pass** over a Geo
knowledge-graph space and produces `Discovery` entities for review.

It mines the space's daily content stream (News stories + AI-podcast episodes + their
Claims), extracts candidate entities, diagnoses **five gap types** (coverage, depth,
freshness, structural, trending) at both entity and theme altitude using exact-name
resolution, ranks them into an integrity track and a growth track, and surfaces a theme
map with depth tiers. See `SKILL.md` for the full 6-stage procedure and guardrails.

- **Read-only** against the Geo GraphQL endpoint, except the final publish stage.
- **Python standard library only** — no install needed (`requirements.txt`).
- **Stateless** — every run is clean-room; it never reads prior-run findings.

## Layout
- `SKILL.md` — the skill contract (stages, I/O, guardrails)
- `scripts/` — harvest, gap_diagnostic, prioritize, theme_heat
- `references/` — NER extraction prompt, Discovery entity schema
