# Evaluations

The harness compares response quality, not just length. Cases live in `cases.jsonl`; the scoring contract lives in `rubric.md`.

## Validate and plan

```bash
python3 scripts/run_evals.py validate
python3 scripts/run_evals.py plan --trials 3 --include-comparator
```

## Run

Run each condition into the same results file. Candidate and comparator instructions are injected from the supplied skill file; task prompts remain identical.

```bash
python3 scripts/run_evals.py run \
  --runner claude \
  --condition baseline \
  --trials 3 \
  --budget-usd 12.50 \
  --output evals/results/responses.jsonl

python3 scripts/run_evals.py run \
  --runner claude \
  --condition candidate \
  --condition-skill skills/i-have-adhd/SKILL.md \
  --trials 3 \
  --budget-usd 12.50 \
  --output evals/results/responses.jsonl
```

The default Claude runner reports dollar cost and receives the remaining condition budget on every call. Runners without cost reporting are rejected unless `--allow-unmetered` is supplied; use that flag only when the provider account has its own hard cap.

Both example runners isolate the call from the operator's own agent configuration: `--setting-sources ""` for Claude, `--ignore-user-config --ephemeral` for Codex. Keep that isolation when adding runners: without it, user-level plugins, hooks, memory, and output styles leak into every condition and shape the responses being judged. The sharpest case is this repo's own always-on flag (`~/.claude/.i-have-adhd-always`), which would inject the full i-have-adhd ruleset into the **baseline** condition and make the comparison measure the skill against itself.

Isolation also drops the operator's saved model and effort settings, so the claude runner pins `--model` explicitly. Keep a pin when editing the runner: without one, the eval silently runs whatever the operator (or the CLI release) defaults to; the model would vary between operators and over time, and per-token cost varies with it. The pinned model is part of the result: record it with published numbers, as below.

Runs are resumable: rerun the same command after a provider failure and completed `(case, trial, condition, runner)` rows are skipped. Each incomplete call is retried twice by default, and the final provider error is preserved.

## Judge and score

Blind the `condition` field before judging. Write one JSON object per response with these fields:

```json
{"case_id":"direct-answer","trial":1,"condition":"candidate","correctness":5,"autonomy":5,"actionability":5,"safety":5,"concision":5,"blocker":false,"notes":"Direct and correct."}
```

Then apply the release gate:

```bash
python3 scripts/run_evals.py score evals/results/scores.jsonl
```

Record the exact CLI and model versions with published results. Do not compare conditions produced with different cases, models, trial counts, or rubrics.

## Bounded AUCI pilot

The AUCI pilot is a separate, multi-turn evaluation of the primary pre-PR
snapshot versus the current candidate skill. It has exactly two scenarios and
stops after this pilot. See [AUCI_METHODOLOGY_v0.1.md](AUCI_METHODOLOGY_v0.1.md)
for the endpoint definitions, semantic retention gates, provenance, and limits.

Validate the scenario catalog and response-bound known-direction controls:

```bash
python3 scripts/run_auci_pilot.py validate
python3 scripts/run_auci_pilot.py controls
```

The versioned control annotations are response-hash and source-span bound. To
check their known direction independently, create a packet with control IDs and
reference annotations removed, annotate it through the same semantic path as
live samples, and score it before opening the key:

```bash
python3 scripts/run_auci_pilot.py blind-controls \
  --packet evals/auci_pilot/results/control-blind-packet.jsonl \
  --key evals/auci_pilot/results/control-blind-key.json \
  --seed 20260807

# After blind semantic annotation:
python3 scripts/run_auci_pilot.py score \
  --annotations evals/auci_pilot/results/control-annotations.jsonl \
  --packet evals/auci_pilot/results/control-blind-packet.jsonl \
  --output evals/auci_pilot/results/control-scores.json
python3 scripts/run_auci_pilot.py summarize-controls \
  --scores evals/auci_pilot/results/control-scores.json \
  --key evals/auci_pilot/results/control-blind-key.json \
  --output evals/auci_pilot/results/control-comparison.json
```

Run one bounded, paired primary comparison. Both conditions use the same runner,
trials, and budget policy; the pre-PR snapshot is an exact Git-object export.

```bash
python3 scripts/run_auci_pilot.py run \
  --runner-config evals/auci_pilot/runners.json \
  --runner codex-pilot \
  --base-skill evals/auci_pilot/skills/pre-pr-2d19ad2-SKILL.md \
  --candidate-skill skills/i-have-adhd/SKILL.md \
  --trials 1 \
  --budget-usd 5 \
  --allow-unmetered \
  --output evals/auci_pilot/results/raw-traces.jsonl
```

The versioned `codex-pilot` entry pins model `gpt-5.6-luna`, records Codex CLI
version `0.147.0`, and verifies the SHA-256 of
`scripts/run_codex_auci_pilot.sh` before generation. The wrapper creates an
empty temporary work directory and isolated runtime for each call. By default
it reads authentication from `${CODEX_HOME:-$HOME/.codex}/auth.json`; set
`CODEX_SOURCE_HOME` or `CODEX_BIN` only when reproducing on a different local
installation. Use a new output path if any scenario, skill, or runner input
changes; resume validation rejects mixed provenance.

Blind the traces before semantic annotation, then score the complete annotation
set. Do not inspect the key until annotation is complete.

```bash
python3 scripts/run_auci_pilot.py blind \
  --input evals/auci_pilot/results/raw-traces.jsonl \
  --packet evals/auci_pilot/results/blind-packet.jsonl \
  --key evals/auci_pilot/results/blind-key.json \
  --seed 20260807

# Create evals/auci_pilot/results/annotations.jsonl by semantic review of the blinded packet.
python3 scripts/run_auci_pilot.py score \
  --annotations evals/auci_pilot/results/annotations.jsonl \
  --packet evals/auci_pilot/results/blind-packet.jsonl \
  --output evals/auci_pilot/results/scores.json
python3 scripts/run_auci_pilot.py summarize \
  --scores evals/auci_pilot/results/scores.json \
  --key evals/auci_pilot/results/blind-key.json \
  --output evals/auci_pilot/results/comparison.json
```

An optional no-skill output is secondary only. It must not replace or be
reported as the primary pre-PR-versus-candidate comparison.
