# AUCI Pilot Design

## Purpose

Build the smallest defensible pilot that can answer whether the revised
`i-have-adhd` skill creates fewer Avoidable User Coordination Interventions
(AUCI) than the pre-PR skill without sacrificing task success, required
substance, or safety.

The pilot measures observable response behavior. It does not measure cognitive
load, ADHD functioning, or cognitive allocation. Cognitive allocation is only
the motivating hypothesis.

## Approaches considered

1. **Shared runner plus a focused pilot module (selected).** Extend the current
   runner with explicit base/candidate/no-skill comparison and reusable runner
   provenance. Add a sibling module for the two multi-turn scenarios and their
   AUCI/substance annotations. This preserves the current suite while keeping
   the new scientific endpoint separate from the old weighted rubric.
2. **Put the complete pilot in `run_evals.py`.** This has fewer files, but it
   mixes single-turn weighted scoring, multi-turn trace generation, AUCI, and
   substantive gates in one already substantial script.
3. **Build an independent pilot harness.** This isolates the pilot, but it
   duplicates condition injection, provider invocation, retry, and provenance
   behavior and makes identical-condition comparisons harder to defend.

## Architecture

### Existing single-turn suite

`scripts/run_evals.py` keeps its current `validate`, `plan`, `run`, and `score`
behavior. Its legacy condition names remain accepted. A new comparison command
takes two explicit files—`--base-skill` and `--candidate-skill`—plus an optional
no-skill condition. It runs the same cases, runner command, trial count, and
budget policy for each condition.

Each response record identifies the exact condition input with the resolved
skill path, SHA-256 content digest, and byte count. The checked-in pre-PR
snapshot is extracted from merge base `2d19ad205eb1d85fc9c3968bdeba4c2116518685`.
The candidate remains `skills/i-have-adhd/SKILL.md`; it must not be edited in
response to pilot results.

### Two-scenario pilot

`scripts/run_auci_pilot.py` reuses the runner invocation and skill-injection
logic. It runs exactly two scenarios:

1. **Interruption recovery:** an agent receives an operational task, then an
   interruption update stating which work is complete and which work remains.
   The pre-specified opportunities concern preserving completed state, avoiding
   repeated work or recap requests, and advancing the remaining agent-owned
   action.
2. **Rationale and caveat preservation:** an agent explains a technical choice,
   then receives a follow-up asking for the next action while preserving the
   decision rationale, compatibility constraint, and rollback caveat. The
   obligations are grounded in the task contract, not in either skill's text.

For each condition, turn two receives the same fixed user update plus that
condition's turn-one response. Raw traces retain both turns and runner metadata.
The hidden evaluation contract is stored beside the scenario but is never sent
to the model.

### Annotation and scoring

Natural-language responses are annotated semantically, not by keyword. An
annotation must address every pre-specified coordination opportunity and every
substantive obligation by stable scenario-owned identifier.

Each coordination opportunity has one primary outcome:

- `0`: the behavior did not require avoidable user repair;
- `1`: the user would have to repair state, sequencing, scope, or an unnecessary
  handoff before the task could continue.

Type and severity remain descriptive only. AUCI is the unweighted sum of binary
opportunities; there is no weighted AUCI score and no coordination-to-substance
ratio.

Substance is scored independently in three semantic classes:

- critical constraints or propositions;
- required propositions or caveats;
- optional enrichment.

The report presents retained/required counts by class. All critical and required
items, task success, and safety must pass their own gates before a condition can
be credited with an AUCI improvement. Every pre-specified opportunity remains
in the denominator after early task failure; an unhandled opportunity requires
repair rather than disappearing from the analysis.

### Blinding and leakage control

The pilot generator emits a blinded review packet without condition names,
skill paths, hashes, or skill contents, plus a separate key. Task prompts are
identical across conditions. Evaluation-contract fields are not included in
generation prompts. The evaluator can justify each obligation from the scenario
task contract and available state without reading the candidate skill.

## Known-direction controls

Versioned semantic behavior fixtures exercise the instrument before live
comparison:

- state-blind behavior loses prior state and increases state-related AUCI;
- over-scaffolded behavior asks for avoidable confirmations or reconstruction
  and is not rewarded merely for adding structure;
- substance-stripped behavior can have low AUCI but fails required-substance
  retention;
- oracle/explicit-state behavior preserves available state and required
  substance and produces the expected lower AUCI;
- early-failure behavior leaves all scenario opportunities present, records the
  repairs needed to continue, and fails the task-success gate.

These controls validate the instrument. They are not comparison conditions.

## Failure handling

Catalog or annotation mismatches fail before scoring. Missing opportunity or
substance identifiers are errors rather than implicit zeros. A provider process
failure preserves the error and does not become an apparently concise response.
A natural-language refusal or premature stop is retained as response behavior
and adjudicated against all pre-specified opportunities and task-success gates.

If known-direction controls do not order sensibly, the instrument is corrected;
the candidate skill is not tuned to the benchmark.

## Verification and report

Automated tests cover legacy behavior, exact skill metadata, comparison
condition construction, scenario validation, complete semantic annotations,
unweighted AUCI, substantive gates, blinding, all controls, and early-failure
handling. The pilot then runs one reproducible trial per base and candidate
condition, with optional no-skill output clearly labeled secondary.

The concise pilot report records commands and versions, links raw traces and
annotations, reports each endpoint separately, states whether the instrument
responded in known directions, identifies remaining annotation ambiguities, and
recommends either one bounded next increment or no expansion. It makes no
statistical non-inferiority or cognitive-effect claim.

## Scope boundary

The work stops after these two scenarios. It does not add a twelve-scenario
suite, specialized LLM judges, weighted quality composite, synthetic ADHD
personas, human subjects, or candidate-skill optimization.
