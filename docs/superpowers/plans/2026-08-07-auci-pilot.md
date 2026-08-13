# AUCI Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reproducible two-scenario pilot comparing the pre-PR and PR skills on AUCI while independently protecting task success, safety, and required substance.

**Architecture:** Preserve the current single-turn CLI and add explicit paired-comparison/provenance support to it. Implement multi-turn trace generation, blinding, semantic annotation validation, AUCI counting, substantive gates, and known-direction controls in a focused sibling module.

**Tech Stack:** Python 3 standard library, `unittest`, JSON/JSONL, Markdown.

## Global Constraints

- The primary comparison is pre-PR `SKILL.md` versus PR `SKILL.md`; no-skill is optional and secondary.
- Do not edit `skills/i-have-adhd/SKILL.md` in response to pilot results.
- Implement exactly two multi-turn scenarios: interruption recovery and rationale/caveat preservation.
- Every coordination opportunity is pre-specified from the task contract and available state.
- AUCI is binary per opportunity and summed without weights.
- Required substance is represented by semantic proposition identifiers, never keyword matching.
- Critical substance, required substance, safety, and task success are independent gates.
- Preserve raw traces and exact skill-content provenance.
- Do not claim cognitive load, ADHD-functioning, cognitive-allocation, or formal statistical effects.
- Stop after this pilot; do not expand the scenario catalog.

---

### Task 1: Explicit skill comparison and provenance

**Files:**
- Modify: `scripts/run_evals.py`
- Modify: `tests/test_run_evals.py`

**Interfaces:**
- Produces: `skill_metadata(path: Path | None) -> dict[str, Any]`
- Produces: `invoke_runner(prompt: str, runner: dict[str, Any], *, retries: int, remaining_budget: float, allow_unmetered: bool) -> dict[str, Any]`
- Produces: `run_comparison(args: argparse.Namespace) -> int`
- Preserves: legacy `validate`, `plan`, `run`, and `score` commands and legacy conditions.

- [ ] **Step 1: Write failing provenance and comparison tests**

```python
def test_skill_metadata_identifies_exact_bytes(self):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "SKILL.md"
        path.write_bytes(b"exact\n")
        self.assertEqual(
            {
                "path": str(path.resolve()),
                "sha256": hashlib.sha256(b"exact\n").hexdigest(),
                "bytes": 6,
            },
            run_evals.skill_metadata(path),
        )

def test_compare_runs_base_candidate_and_optional_no_skill(self):
    # Use a text stub runner and one temporary case. Assert output conditions
    # are ["base", "candidate", "no_skill"], base/candidate hashes differ,
    # and no_skill contains {"mode": "no_skill"}.
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `python3 -m unittest tests.test_run_evals.EvaluationHarnessTest.test_skill_metadata_identifies_exact_bytes tests.test_run_evals.EvaluationHarnessTest.test_compare_runs_base_candidate_and_optional_no_skill -v`

Expected: errors because `skill_metadata` and `run_comparison` do not exist.

- [ ] **Step 3: Add exact metadata, a reusable invocation seam, and compare CLI**

```python
def skill_metadata(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"mode": "no_skill"}
    data = path.read_bytes()
    return {
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
    }

def run_comparison(args: argparse.Namespace) -> int:
    conditions = [("base", args.base_skill), ("candidate", args.candidate_skill)]
    if args.include_no_skill:
        conditions.append(("no_skill", None))
    for condition, skill in conditions:
        run_args = argparse.Namespace(**vars(args), condition=condition, condition_skill=skill)
        status = run_evaluations(run_args)
        if status:
            return status
    return 0
```

Treat both `baseline` and `no_skill` as no-skill prompt conditions; require a
skill file for `base`, `candidate`, and `comparator`. Add `skill` and
`task_sha256` metadata to every new response row without removing legacy fields.

- [ ] **Step 4: Run focused and legacy tests and confirm GREEN**

Run: `python3 -m unittest tests.test_run_evals -v`

Expected: all evaluation-harness tests pass, including the existing nine.

- [ ] **Step 5: Commit the comparator change**

```bash
git add scripts/run_evals.py tests/test_run_evals.py
git commit -m "feat: compare explicit evaluation skills"
```

If the managed sandbox still makes `.git` read-only, retain the working-tree
changes and record that constraint; do not bypass it.

### Task 2: Pilot schema, AUCI, substantive gates, and controls

**Files:**
- Create: `scripts/run_auci_pilot.py`
- Create: `tests/test_run_auci_pilot.py`
- Create: `evals/auci_pilot/scenarios.json`
- Create: `evals/auci_pilot/known_direction_controls.json`

**Interfaces:**
- Produces: `load_scenarios(path: Path) -> dict[str, dict[str, Any]]`
- Produces: `score_annotation(scenario: dict[str, Any], annotation: dict[str, Any]) -> dict[str, Any]`
- Produces: `score_controls(scenarios: dict[str, dict[str, Any]], controls: list[dict[str, Any]]) -> list[dict[str, Any]]`

- [ ] **Step 1: Write failing validation and scoring tests**

```python
def test_annotation_requires_every_predeclared_id(self):
    with self.assertRaisesRegex(ValueError, "coordination opportunity ids"):
        pilot.score_annotation(self.scenario, self.annotation_without_one_opportunity)

def test_auci_is_unweighted_binary_sum(self):
    result = pilot.score_annotation(self.scenario, self.complete_annotation)
    self.assertEqual(1, result["auci_total"])
    self.assertNotIn("weighted_auci", result)

def test_optional_enrichment_does_not_gate_eligibility(self):
    result = pilot.score_annotation(self.scenario, self.annotation_without_optional)
    self.assertTrue(result["gates"]["eligible"])
```

Add catalog tests asserting there are exactly two scenarios and every
opportunity can be justified from its scenario task contract without any skill
text field.

- [ ] **Step 2: Run the new test module and confirm RED**

Run: `python3 -m unittest tests.test_run_auci_pilot -v`

Expected: import failure because `run_auci_pilot.py` does not exist.

- [ ] **Step 3: Implement exact-set validation and separate endpoints**

```python
def score_annotation(scenario, annotation):
    expected_auci = {item["id"] for item in scenario["coordination_opportunities"]}
    observed_auci = {item["opportunity_id"] for item in annotation["coordination"]}
    if expected_auci != observed_auci:
        raise ValueError("coordination opportunity ids must match the scenario exactly")
    auci_total = sum(item["auci"] for item in annotation["coordination"])
    # Validate each outcome is the integer 0 or 1, require nonempty evidence,
    # score critical/required/optional obligations independently, and construct
    # task_success, safety, critical_substance, required_substance, eligible gates.
```

Missing, duplicate, or unknown identifiers are errors. `retained`, `omitted`,
and `contradicted` are the only substance statuses. Optional enrichment is
reported but does not gate eligibility.

- [ ] **Step 4: Add exactly two scenarios and five control behaviors**

The scenario IDs are `interruption-recovery` and
`rationale-caveat-preservation`. Each contains two fixed user turns, hidden
coordination opportunities, and semantic obligations grouped as `critical`,
`required`, and `optional`.

The control IDs are `state-blind`, `over-scaffolded`, `substance-stripped`,
`oracle-explicit-state`, and `early-failure`. Each fixture contains concrete
assistant response text plus a complete semantic annotation.

- [ ] **Step 5: Assert known-direction behavior and confirm GREEN**

```python
self.assertGreater(by_id["state-blind"]["auci_total"], by_id["oracle-explicit-state"]["auci_total"])
self.assertGreater(by_id["over-scaffolded"]["auci_total"], 0)
self.assertFalse(by_id["substance-stripped"]["gates"]["required_substance"])
self.assertFalse(by_id["early-failure"]["gates"]["task_success"])
self.assertFalse(by_id["early-failure"]["gates"]["eligible"])
```

Run: `python3 -m unittest tests.test_run_auci_pilot -v`

Expected: all schema, scoring, and directionality tests pass.

### Task 3: Multi-turn generation and blind review packets

**Files:**
- Modify: `scripts/run_auci_pilot.py`
- Modify: `tests/test_run_auci_pilot.py`

**Interfaces:**
- Consumes: `run_evals.invoke_runner`, `run_evals.skill_metadata`
- Produces: `run_pilot(args: argparse.Namespace) -> int`
- Produces: `blind_traces(rows: list[dict[str, Any]], seed: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]`

- [ ] **Step 1: Write a failing two-turn end-to-end test with a stub runner**

```python
def test_run_pilot_executes_two_turns_for_each_primary_condition(self):
    # A shell-free Python stub returns the prompt it receives. Run one scenario
    # for base and candidate. Assert two provider calls per condition, identical
    # fixed user turns, condition-specific turn-one responses in turn two, and
    # exact skill hashes in both trace rows.
```

Also write a blinding test that recursively confirms `condition`, `skill`, and
skill hashes occur only in the key, never in the review packet.

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `python3 -m unittest tests.test_run_auci_pilot.PilotTest.test_run_pilot_executes_two_turns_for_each_primary_condition tests.test_run_auci_pilot.PilotTest.test_blind_packet_has_no_condition_metadata -v`

Expected: failures because generation and blinding functions do not exist.

- [ ] **Step 3: Implement transcript rendering, paired execution, and blinding**

Render turns with neutral `<conversation>` XML containing only role/content
pairs. Apply the condition skill outside the conversation with the existing
skill wrapper. Save one row per scenario/trial/condition with the two user turns,
two assistant responses, runner name, invocation metadata, usage/cost, and exact
skill metadata.

Shuffle trace rows using `random.Random(seed)` and assign opaque IDs
`sample-001`, `sample-002`, and so on. The packet retains scenario task content
and assistant responses; the separate key retains condition and skill metadata.

- [ ] **Step 4: Add CLI commands and confirm GREEN**

Commands:

```bash
python3 scripts/run_auci_pilot.py validate
python3 scripts/run_auci_pilot.py controls
python3 scripts/run_auci_pilot.py run --runner-config evals/auci_pilot/runners.json --runner codex-pilot --base-skill evals/auci_pilot/skills/pre-pr-2d19ad2-SKILL.md --candidate-skill skills/i-have-adhd/SKILL.md --trials 1 --budget-usd 5 --allow-unmetered --output evals/auci_pilot/results/raw-traces.jsonl
python3 scripts/run_auci_pilot.py blind --input evals/auci_pilot/results/raw-traces.jsonl --packet evals/auci_pilot/results/blind-packet.jsonl --key evals/auci_pilot/results/blind-key.json --seed 20260807
python3 scripts/run_auci_pilot.py score --annotations evals/auci_pilot/results/annotations.jsonl --packet evals/auci_pilot/results/blind-packet.jsonl --output evals/auci_pilot/results/scores.json
```

Run: `python3 -m unittest tests.test_run_auci_pilot -v`

Expected: the stub end-to-end trace and blinding tests pass without network.

### Task 4: Methodology, base artifact, and usage documentation

**Files:**
- Create: `evals/AUCI_METHODOLOGY_v0.1.md`
- Create: `evals/auci_pilot/skills/pre-pr-2d19ad2-SKILL.md`
- Modify: `evals/README.md`

**Interfaces:**
- Consumes: base skill content from Git object `2d19ad205eb1d85fc9c3968bdeba4c2116518685:skills/i-have-adhd/SKILL.md`
- Documents: the exact commands produced in Task 3.

- [ ] **Step 1: Add the methodology with complete provenance**

It must state the formal engineering claim, AUCI definition, semantic
Required-Substance Retention, substantive/safety/task-success gates, observable
versus hypothesized endpoints, benchmark limitations, and both supplied
attributions verbatim in substance:

- GPT-5.6 Sol Extra High / ChatGPT conversation: coordination-work and
  cognitive-allocation framing.
- GPT-5.6 Sol Pro / branched ChatGPT conversation: formal methodology, AUCI,
  and implementation specification.

Do not invent conversation IDs, dates, URLs, or authors.

- [ ] **Step 2: Add the exact pre-PR skill snapshot and verify its blob**

Run:

```bash
git show 2d19ad205eb1d85fc9c3968bdeba4c2116518685:skills/i-have-adhd/SKILL.md > /tmp/pre-pr-SKILL.md
cmp /tmp/pre-pr-SKILL.md evals/auci_pilot/skills/pre-pr-2d19ad2-SKILL.md
sha256sum /tmp/pre-pr-SKILL.md evals/auci_pilot/skills/pre-pr-2d19ad2-SKILL.md
```

The repository file must byte-match the Git object. Use `apply_patch` to add the
repository file; the temporary extraction is verification only.

- [ ] **Step 3: Document old and new eval paths**

Keep current single-turn commands. Add a bounded AUCI pilot section showing
validation, controls, primary comparison, blinding, annotation, and scoring.
State explicitly that no-skill is secondary and that the pilot stops at two
scenarios.

- [ ] **Step 4: Validate documentation invariants**

Run:

```bash
rg -n "GPT-5.6 Sol Extra High|GPT-5.6 Sol Pro|observable|hypothes" evals/AUCI_METHODOLOGY_v0.1.md
git diff --check
```

Expected: both attributions and the endpoint distinction are present; no
whitespace errors.

### Task 5: Live pilot, semantic adjudication, and report

**Files:**
- Create: `evals/auci_pilot/results/raw-traces.jsonl`
- Create: `evals/auci_pilot/results/blind-packet.jsonl`
- Create: `evals/auci_pilot/results/blind-key.json`
- Create: `evals/auci_pilot/results/annotations.jsonl`
- Create: `evals/auci_pilot/results/scores.json`
- Create: `evals/AUCI_PILOT_REPORT.md`

**Interfaces:**
- Consumes: the CLI and artifacts from Tasks 1–4.
- Produces: reproducible evidence for each definition-of-done item.

- [ ] **Step 1: Record tool versions and run deterministic gates**

```bash
python3 --version
codex --version
python3 scripts/run_evals.py validate
python3 scripts/run_auci_pilot.py validate
python3 scripts/run_auci_pilot.py controls
python3 -m unittest discover -s tests -v
```

- [ ] **Step 2: Run one live paired trial and preserve raw traces**

Use the pinned model supported by the local Codex CLI if available. Run base and
candidate under the identical runner command. Include no-skill only if it does
not distract from the primary comparison.

- [ ] **Step 3: Blind and semantically annotate every sample**

Create the packet/key with seed `20260807`. Annotate every opportunity and
substance obligation with nonempty response evidence. Do not inspect the key
until the annotation file is complete.

- [ ] **Step 4: Score and write the concise pilot report**

Report known-direction controls, base versus candidate AUCI by opportunity,
substance/task/safety gates, condition leakage checks, actual limitations, and
the recommendation for only the next bounded increment. Do not collapse the
endpoints or claim statistical/cognitive effects.

- [ ] **Step 5: Run the requirement-by-requirement completion audit**

```bash
python3 -m unittest discover -s tests -v
python3 scripts/run_evals.py validate
python3 scripts/run_auci_pilot.py validate
python3 scripts/run_auci_pilot.py controls
python3 scripts/run_auci_pilot.py score --annotations evals/auci_pilot/results/annotations.jsonl --packet evals/auci_pilot/results/blind-packet.jsonl --output /tmp/auci-scores.json
cmp /tmp/auci-scores.json evals/auci_pilot/results/scores.json
git diff --check
git status --short
```

Map each of the ten definition-of-done items to an inspected file or fresh
command result. Completion is not established by tests alone.
