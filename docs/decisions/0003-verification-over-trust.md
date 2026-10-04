# 0003 — Verification over trust: references are checked in code, not requested in prompts

Date: 2026-10-04. Status: accepted. Code: [`pipeline/verify.py`](../../src/changelog_forge/pipeline/verify.py).

## Context

Release notes are only useful if every item links to the commit or pull request it came
from, and a link to the wrong PR is worse than no link: it is a confident false statement
with a URL attached. Language models produce exactly that failure. They pattern-match a
plausible `#1234`, they cite PR numbers mentioned *inside* a body ("Backport of: #13535")
that are not in the range, and they reformat references (bare `5479` instead of `#5479`).

The options were to ask harder (prompt rules, a second "please double-check" call) or to
check deterministically.

## Decision

The model is trusted to write; it is not trusted to cite. After the map step, every
reference is resolved against the set collected from GitHub (`RefIndex`):

- `#123`, `PR #123`, `pull/123`, a PR URL, and a bare number of up to 6 digits resolve to a
  PR **only if** that PR is in the range;
- a SHA prefix (7+ hex) or commit URL resolves only if it uniquely matches a collected
  commit; a SHA belonging to a PR is canonicalised to the PR;
- anything else is **dropped and recorded** in `verified.dropped_refs`, never "corrected"
  by guessing; a change left with no valid reference is dropped (`dropped_items`);
- an input the model skipped gets a deterministic fallback item (`uncovered_inputs`), so a
  change can disappear from the notes only by being a branch-sync merge.

The same principle applies to the other checkable properties:

- **breaking**: needs `breaking_confidence >= 0.6`; below that it is "Possibly breaking" in
  the developer document and not presented as breaking to users (`verified.downgraded`);
- **structure**: the reducer orders items and writes prose but cannot move an item to
  another section or invent one; placement comes from the item's own verified facts;
- **length**: per-field budgets, trimmed at a word boundary and recorded (`trimmed`).

The prompts still forbid inventing references (cheap, and it lowers the drop rate), but the
guarantee comes from code.

## Why not a second model pass

A "verify your references" call costs another full-price request, adds latency, and is
itself a model output that can be wrong in the same way. The set of valid references is
known exactly; checking membership in it is a dictionary lookup. Use a model for judgement,
use code for facts.

## Evidence

- Live smoke run 2 (honojs/hono, 20 commits): gpt-oss-20b emitted bare numbers for 11
  references. The first verifier dropped all 11 (correct by its rules, but it lost good
  links and produced one fallback item). Canonicalising bare numbers that exist in the
  range fixed it without trusting anything new: they are still checked against the set.
- The pydantic golden case is backports whose bodies cite PRs outside the range; the
  `hallucinated_refs` scorer (must be 0) and the forbidden-claim regex `#13[0-9]{3}` check
  that none reach the documents.

## Consequences

- `hallucinated_refs = 0` is a hard gate in `uv run evals`, and it holds by construction;
  the interesting number becomes `dropped` (how often the model tried), tracked per case.
- The verification report is part of the API response (`verified`) and shown in the UI, so
  a reader can see what was removed and why.
- Free-text claims inside summaries (a version number, a feature name) are not verified by
  code; the golden set's `forbidden_claims` and the LLM judge's faithfulness score cover
  them, imperfectly.
