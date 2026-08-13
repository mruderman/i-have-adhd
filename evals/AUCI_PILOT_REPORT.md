# AUCI Pilot Report

## Decision

The AUCI measurement architecture is coherent and executable enough for **one
bounded calibration increment**, but not for expansion to a twelve-scenario
benchmark yet.

The live pilot did not show an advantage for the PR skill. Base and candidate
each produced `1` AUCI across `6` pre-specified opportunities. Both retained all
critical substance, retained `4/5` required propositions, passed safety in both
scenarios, and failed eligibility in the rationale/caveat scenario. No claim of
candidate improvement, non-inferiority, cognitive effect, ADHD functioning, or
cognitive allocation is supported.

## Run provenance

- Date: 2026-08-07 (America/Los_Angeles)
- Python: `3.12.3`
- Codex CLI: `0.147.0`
- Model: `gpt-5.6-luna`
- Trials: one per condition and scenario
- Primary conditions only: pre-PR base and PR candidate; no no-skill run
- Base Git object:
  `2d19ad205eb1d85fc9c3968bdeba4c2116518685:skills/i-have-adhd/SKILL.md`
- Base skill SHA-256:
  `cae8c063977214b372c6897b7c93ac8faa573214a8635896f767e3bac092adf8`
- Candidate commit: `f41eaf04c57d54b11d6ebcabcbfd00ffeff21444`
- Candidate skill SHA-256:
  `e83f709760fe5840f0621f75c9e7d683e42a737e70e40c83e9f52e49d48c1e75`
- Runner: `codex-pilot`
- Runner-config SHA-256:
  `ac39b36787ecd12d7ad6153fc194cec66faa69b0aa1c831d4e4c04d8a8345292`
- Runner wrapper SHA-256:
  `35999eb238486c65804214d6bb3b0aa2f2606248ea2811fcf64c6b0349580789`

The Codex runner used a fresh writable temporary runtime containing only a
symlink to existing authentication. It ran from an empty directory outside the
repository with user config, project rules, plugins, goals, memories, and
workspace dependencies disabled. The reproducible command uses the checked-in
`evals/auci_pilot/runners.json` and `scripts/run_codex_auci_pilot.sh`; the
runner configuration verifies the wrapper hash before generation. Its pinned
invocation and digest are preserved in each raw turn.

## Known-direction validation

Five behaviors were reviewed twice: once as response-hash/source-span-bound
reference calibrations and once through a separately blinded packet with
control IDs and expected annotations removed. The same semantic scoring path
used for live samples scored the blinded controls.

| Control | Independently reviewed AUCI | Required-substance gate | Task-success gate | Expected direction |
| --- | ---: | --- | --- | --- |
| State-blind | 3/3 | Fail | Fail | Worse than oracle |
| Over-scaffolded | 2/3 | Fail | Fail | Detectable, not rewarded |
| Substance-stripped | 2/3 | Fail | Fail | Retention failure detected |
| Oracle/explicit-state | 0/3 | Pass | Pass | Better than state-blind |
| Early failure | 3/3 | Fail | Fail | Cannot gain from disappearing opportunities |

All required directional checks passed. Early failure retained every
pre-specified opportunity and required repair on all three.

The reference calibration had assigned substance-stripped behavior `0/3` AUCI,
while the independent blind review assigned `2/3`. The evaluator judged that
omitting supplied coexistence and rollback constraints would itself force user
repair. This disagreement is informative: AUCI and substantive omission can
overlap even though their numeric endpoints remain separate.

## Live base-versus-candidate result

| Condition | AUCI | Critical retained | Required retained | Safety | All samples eligible |
| --- | ---: | ---: | ---: | --- | --- |
| Pre-PR base | 1/6 | 3/3 | 4/5 | 2/2 pass | No |
| PR candidate | 1/6 | 3/3 | 4/5 | 2/2 pass | No |

Scenario detail was identical by condition:

| Scenario | AUCI | Substance/task result |
| --- | ---: | --- |
| Interruption recovery | 0/3 | Critical 2/2; required 2/2; all gates pass |
| Rationale/caveat preservation | 1/3 | Critical 1/1; required 2/3; task-success and eligibility fail |

In the interruption scenario, both conditions preserved the completed schema
migration and API health check, identified browser smoke as the only remaining
check, and provided the exact fictional command
`npm run test:smoke -- --project=chromium` plus the pass/fail recording rule for
`release-evidence/browser-smoke.txt` without asking the user to reconstruct
state.

In the rationale/caveat scenario, both final responses preserved old/new token
coexistence, the rollback path, and a concrete adapter instruction. Both omitted
the supplied reason for the staged adapter—limiting blast radius—from the final
artifact despite the second user turn explicitly asking to preserve it. The
blinded evaluator therefore recorded one repair, one missing required
proposition, and task failure for both conditions.

## What worked

- Exact base and candidate skill bytes were frozen before generation, hashed,
  and tied to runner/task provenance; stale resume rows are rejected.
- Exactly two multi-turn scenarios executed end to end with two assistant turns
  per condition and raw provider prompts retained.
- Coordination opportunities and semantic substance obligations were declared
  before generation and grounded to exact excerpts in user-visible task turns.
- AUCI remained an unweighted binary outcome per opportunity. Substance, task
  success, and safety remained independent, inspectable gates.
- Blinded packets excluded condition, skill, runner, hashes, provider prompts,
  and reference control labels. Annotation hashes and source spans prevent an
  annotation from being silently reused for a different response.
- The separate blind key retains runner and scenario digests. Unblinding rejects
  mixed runners/configurations, duplicate condition/scenario/trial rows, and
  non-identical provenance-bound coverage across conditions.

## What did not work or remains ambiguous

- One evaluator and one trial cannot establish reliability or a stable effect.
- Substance omission can also create user repair, so AUCI and retention are
  conceptually distinct but not behaviorally disjoint.
- Listing checks as completed and one as remaining was not treated as the
  optional explicit statement that completed checks need not be rerun.
- A result-recording rule inside a release-verification handoff was treated as
  occurring before release even when those words were not repeated verbatim.
- Rationale present in turn one but absent from the explicitly requested final
  handoff was treated as omitted. The benchmark needs a written retention-window
  rule so different evaluators make the same decision.
- In the over-scaffolded control, asking the user to confirm browser smoke was
  “next” was not treated as retaining that it was the only remaining check.
- The isolated Codex system still reported its built-in system-skill catalog;
  user/project skill sources were disabled and conditions were otherwise
  identical, but system-prompt effects remain a runner limitation.

## Recommendation and stop condition

Do not expand to the full benchmark and do not tune the candidate skill to these
outputs.

The next increment should keep these same two scenarios and add a short
adjudication manual covering: when substance omission also counts as AUCI,
whether a prior-turn proposition must be repeated in the requested final
artifact, and how implicit release timing or no-rerun state should be scored.
Re-annotate the frozen blind packets with that manual and measure agreement
before adding scenarios.

This report stops after the pilot.

## Evidence artifacts

- Methodology: `evals/AUCI_METHODOLOGY_v0.1.md`
- Scenarios: `evals/auci_pilot/scenarios.json`
- Runner configuration/wrapper: `evals/auci_pilot/runners.json`,
  `scripts/run_codex_auci_pilot.sh`
- Raw traces: `evals/auci_pilot/results/raw-traces.jsonl`
- Live blind packet/key: `blind-packet.jsonl`, `blind-key.json`
- Live annotations/scores/comparison: `annotations.jsonl`, `scores.json`,
  `comparison.json`
- Control blind packet/key: `control-blind-packet.jsonl`,
  `control-blind-key.json`
- Control annotations/scores/comparison: `control-annotations.jsonl`,
  `control-scores.json`, `control-comparison.json`
