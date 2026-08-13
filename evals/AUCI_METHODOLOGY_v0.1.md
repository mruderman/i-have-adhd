# AUCI Methodology v0.1

## Formal engineering claim

This two-scenario pilot tests the engineering claim that the revised
`i-have-adhd` skill elicits fewer Avoidable User Coordination Interventions
(AUCI) than the pre-PR skill, without materially degrading task success,
required substantive content, or safety.

The primary comparison is the checked-in pre-PR `SKILL.md` snapshot versus the
PR `skills/i-have-adhd/SKILL.md`. A no-skill condition may be generated as a
secondary comparator, but it is not the primary PR comparison.

## Measurement model

A **coordination opportunity** is an agent obligation pre-specified from the
scenario task contract and the state available to the agent. It must be
justifiable without reading either skill's wording.

For each opportunity, the annotation records one binary AUCI outcome:

- `0`: the agent handled the opportunity without requiring an avoidable user
  repair.
- `1`: the user would need to repair state, sequencing, scope, or an
  unnecessary handoff before the work could continue.

Severity and type are descriptive metadata only. AUCI is the unweighted sum of
these binary outcomes. It is not a weighted score and is not a ratio of
coordination to substantive behavior. Early task failure does not remove an
opportunity from scoring; it records the repair needed and separately fails the
task-success gate.

## Required-Substance Retention and non-regression gates

Required-Substance Retention is evaluated semantically using stable,
scenario-owned proposition identifiers, never keyword matching. Each
obligation is annotated as `retained`, `omitted`, or `contradicted`, and must
include response evidence. Obligations are classified independently as:

- **Critical:** constraints or propositions that must be preserved.
- **Required:** propositions or caveats that must be preserved.
- **Optional:** useful enrichment that is reported but does not determine
  eligibility.

The following gates remain separate:

1. Task success
2. Safety
3. Critical-substance retention
4. Required-substance retention

A condition receives credit for an AUCI improvement only when all four gates
pass. Better coordination cannot be credited by deleting required substance,
failing the task early, or compromising safety.

## Pilot design and provenance

The pilot has exactly two multi-turn scenarios: interruption recovery and
rationale/caveat preservation. For each condition, the second turn receives
the same fixed user update plus that condition's first response. Raw traces
retain both turns, runner metadata, and exact skill-content provenance:
resolved path, SHA-256 digest, and byte count. The pre-PR artifact is the exact
content of Git object
`2d19ad205eb1d85fc9c3968bdeba4c2116518685:skills/i-have-adhd/SKILL.md`.
The live runner is the versioned `codex-pilot` configuration in
`evals/auci_pilot/runners.json`; generation verifies the declared runner-script
SHA-256 before making a provider call.

Review packets are blinded: they contain task content and responses but no
condition name, skill path, digest, or skill content. A separate key retains
that information plus the scenario and runner-configuration digests. After
annotation, unblinding rejects duplicate condition/scenario/trial rows, mixed
runners or configurations, and anything other than identical provenance-bound
coverage across conditions. The scenario's hidden evaluation contract is not
sent to the model.

Known-direction controls test the instrument rather than competing with the
PR: state-blind behavior should worsen state-related AUCI; oracle/explicit-state
behavior should improve it; substance-stripped behavior should fail retention;
over-scaffolding should be detectable rather than rewarded automatically; and
early failure should fail task success while retaining every opportunity.
Reference control annotations are bound to the exact response SHA-256 and
response excerpts. A separate blinded packet removes control IDs and reference
annotations so the behaviors can be independently re-annotated through the same
semantic path used for live samples. This is a calibration of the annotation
instrument, not a deterministic natural-language classifier.

The two tasks require completed response artifacts: an operational
release-verification handoff and a concrete implementation instruction. They do
not award task success for promising an external action that the isolated runner
cannot perform.

## Observable endpoints and hypothesis boundary

Observable endpoints are AUCI by pre-specified opportunity,
critical/required/optional semantic retention, task-success and safety gates,
condition-leakage checks, and known-direction control behavior.

The motivating hypothesis is that better support for coordination work may
leave more cognitive allocation for substantive work. The pilot does **not**
measure cognitive load, ADHD functioning, cognitive allocation, human
outcomes, or a formal statistical effect. It does not establish cognitive
mechanisms from response behavior.

## Limitations and stop condition

This is a minimal, two-scenario engineering pilot, not a general benchmark. It
uses blinded semantic annotation by one evaluator, a small pre-specified catalog, one bounded
paired comparison, and model/runner behavior that can vary over time. It does
not support statistical non-inferiority, population claims, synthetic ADHD
personas, specialized judge ensembles, or a weighted quality composite.

The work stops after this pilot. If the controls or gates do not behave
sensibly, correct the instrument rather than tuning the candidate skill to the
benchmark. Any next step must be a separately approved, bounded increment.

## Methodology provenance

The coordination-work and cognitive-allocation framing was developed in a
**GPT-5.6 Sol Extra High / ChatGPT conversation**.

The formal methodology, AUCI construct, and implementation specification were
developed in a **GPT-5.6 Sol Pro / branched ChatGPT conversation**.

No conversation identifiers, dates, URLs, or author identities are asserted
because none were supplied.
