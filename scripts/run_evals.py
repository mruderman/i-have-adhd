#!/usr/bin/env python3
"""Validate, run, and score paired response-quality evaluations."""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import subprocess
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "evals" / "cases.jsonl"
WEIGHTS = {
    "correctness": 0.35,
    "autonomy": 0.25,
    "actionability": 0.20,
    "safety": 0.10,
    "concision": 0.10,
}
CONDITIONS = {"base", "baseline", "candidate", "comparator", "no_skill"}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}: line {number}: {exc.msg}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"{path}: line {number}: expected a JSON object")
        rows.append(row)
    return rows


def load_cases(path: Path = DEFAULT_CASES) -> list[dict[str, Any]]:
    return read_jsonl(path)


@dataclass(frozen=True)
class _SkillSnapshot:
    path: Path | None
    data: bytes | None

    def metadata(self) -> dict[str, Any]:
        if self.data is None:
            return {"mode": "no_skill"}
        assert self.path is not None
        return {
            "path": str(self.path.resolve()),
            "sha256": hashlib.sha256(self.data).hexdigest(),
            "bytes": len(self.data),
        }

    def instructions(self) -> str:
        if self.data is None:
            raise ValueError("A skill file is required for this condition")
        return self.data.decode("utf-8")


def _load_skill_snapshot(path: Path | None) -> _SkillSnapshot:
    if path is None:
        return _SkillSnapshot(path=None, data=None)
    return _SkillSnapshot(path=path, data=path.read_bytes())


def skill_metadata(path: Path | None) -> dict[str, Any]:
    return _load_skill_snapshot(path).metadata()


def runner_config_sha256(runner: dict[str, Any]) -> str:
    canonical = json.dumps(
        runner,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def completed_keys(rows: list[dict[str, Any]]) -> set[tuple[str, int, str, str]]:
    keys: set[tuple[str, int, str, str]] = set()
    for row in rows:
        fields = (row.get("case_id"), row.get("trial"), row.get("condition"), row.get("runner"))
        if isinstance(fields[0], str) and isinstance(fields[1], int) and all(
            isinstance(value, str) for value in fields[2:]
        ):
            keys.add(fields)  # type: ignore[arg-type]
    return keys


def validate_cases(cases: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    required = {"id", "category", "prompt", "risk", "criteria"}
    for index, case in enumerate(cases, start=1):
        missing = sorted(required - set(case))
        if missing:
            errors.append(f"Case {index}: missing fields: {', '.join(missing)}")
            continue
        case_id = case["id"]
        if not isinstance(case_id, str) or not case_id:
            errors.append(f"Case {index}: id must be a non-empty string")
        elif case_id in seen:
            errors.append(f"Duplicate case id: {case_id}")
        else:
            seen.add(case_id)
        if case["risk"] not in {"low", "medium", "high"}:
            errors.append(f"Case {case_id}: risk must be low, medium, or high")
        if not isinstance(case["criteria"], list) or not case["criteria"]:
            errors.append(f"Case {case_id}: criteria must be a non-empty list")
    return errors


def _validate_score(row: dict[str, Any], index: int) -> None:
    required = {"case_id", "trial", "condition", *WEIGHTS, "blocker", "notes"}
    missing = sorted(required - set(row))
    if missing:
        raise ValueError(f"Score row {index}: missing fields: {', '.join(missing)}")
    if row["condition"] not in CONDITIONS:
        raise ValueError(f"Score row {index}: unsupported condition {row['condition']!r}")
    for metric in WEIGHTS:
        value = row[metric]
        if not isinstance(value, (int, float)) or not 1 <= value <= 5:
            raise ValueError(f"Score row {index}: {metric} must be between 1 and 5")
    if not isinstance(row["blocker"], bool):
        raise ValueError(f"Score row {index}: blocker must be boolean")


def _describe_rows(keys: list[tuple[str, Any]]) -> str:
    return ", ".join(f"{case_id}/trial {trial}" for case_id, trial in keys)


def _check_pairing(
    grouped: dict[str, list[dict[str, Any]]], reference_condition: str
) -> None:
    """Conditions are only comparable when judged on identical rows."""
    coverage = {
        condition: Counter((row["case_id"], row["trial"]) for row in rows)
        for condition, rows in grouped.items()
    }
    for condition, counts in sorted(coverage.items()):
        repeated = sorted(key for key, count in counts.items() if count > 1)
        if repeated:
            raise ValueError(
                f"{condition}: duplicate score rows for {_describe_rows(repeated)}"
            )
    reference = coverage[reference_condition]
    for condition, counts in sorted(coverage.items()):
        if condition == reference_condition or counts == reference:
            continue
        details = []
        missing = sorted(set(reference) - set(counts))
        if missing:
            details.append(f"missing {_describe_rows(missing)}")
        unmatched = sorted(set(counts) - set(reference))
        if unmatched:
            details.append(f"unmatched {_describe_rows(unmatched)}")
        raise ValueError(
            f"{condition} was not judged on the same rows as {reference_condition}: "
            + "; ".join(details)
        )


def summarize_scores(scores: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for index, row in enumerate(scores, start=1):
        _validate_score(row, index)
        grouped[row["condition"]].append(row)
    reference_conditions = [
        condition for condition in ("baseline", "base") if condition in grouped
    ]
    if len(reference_conditions) != 1:
        raise ValueError(
            "Scores must include exactly one reference condition: baseline or base"
        )
    if "candidate" not in grouped:
        raise ValueError("Scores must include a candidate condition")
    reference_condition = reference_conditions[0]
    _check_pairing(grouped, reference_condition)

    conditions: dict[str, dict[str, Any]] = {}
    for condition, rows in sorted(grouped.items()):
        metrics = {
            metric: sum(float(row[metric]) for row in rows) / len(rows)
            for metric in WEIGHTS
        }
        conditions[condition] = {
            "rows": len(rows),
            **metrics,
            "weighted_score": sum(metrics[metric] * weight for metric, weight in WEIGHTS.items()),
            "blocking_findings": sum(bool(row["blocker"]) for row in rows),
        }

    reference = conditions[reference_condition]
    candidate = conditions["candidate"]
    reasons: list[str] = []
    if candidate["blocking_findings"]:
        reasons.append("Candidate has blocking safety or correctness findings.")
    if candidate["correctness"] < reference["correctness"] - 0.1:
        reasons.append("Candidate correctness regressed by more than 0.1 points.")
    if candidate["safety"] < reference["safety"] - 0.1:
        reasons.append("Candidate safety regressed by more than 0.1 points.")
    if candidate["weighted_score"] <= reference["weighted_score"]:
        reasons.append(
            f"Candidate weighted score did not beat {reference_condition}."
        )

    return {
        "weights": WEIGHTS,
        "conditions": conditions,
        "release_gate": {"passed": not reasons, "reasons": reasons},
    }


def _condition_prompt_from_snapshot(
    task: str, condition: str, skill_snapshot: _SkillSnapshot
) -> str:
    if condition in {"baseline", "no_skill"}:
        return task
    if skill_snapshot.data is None:
        raise ValueError(f"--condition-skill is required for the {condition} condition")
    return (
        "Follow the response-style skill below while completing the task. "
        "Do not discuss or quote the skill.\n\n"
        f"<response_style>\n{skill_snapshot.instructions()}\n</response_style>\n\n"
        f"<task>\n{task}\n</task>"
    )


def _condition_prompt(task: str, condition: str, skill_path: Path | None) -> str:
    if condition in {"baseline", "no_skill"}:
        return task
    return _condition_prompt_from_snapshot(task, condition, _load_skill_snapshot(skill_path))


def _resume_skill_identity(metadata: Any) -> dict[str, str] | None:
    if not isinstance(metadata, dict):
        return None
    mode = metadata.get("mode")
    if mode == "no_skill":
        return {"mode": "no_skill"}
    sha256 = metadata.get("sha256")
    if isinstance(sha256, str):
        return {"sha256": sha256}
    return None


def _validate_resume_provenance(
    row: dict[str, Any],
    *,
    task_sha256: str,
    skill: dict[str, Any],
    runner_config_digest: str,
) -> None:
    expected_skill = _resume_skill_identity(skill)
    actual_skill = _resume_skill_identity(row.get("skill"))
    if (
        row.get("task_sha256") != task_sha256
        or actual_skill != expected_skill
        or row.get("runner_config_sha256") != runner_config_digest
    ):
        raise ValueError(
            "Completed row provenance mismatch; use a new output path for changed task, "
            "skill, or runner configuration."
        )


def _parse_response(output: str, response_format: str) -> tuple[str, dict[str, Any], float | None]:
    if response_format == "text":
        return output.strip(), {}, None
    if response_format == "claude-json":
        payload = json.loads(output)
        return (
            str(payload.get("result", "")).strip(),
            payload.get("usage", {}) or {},
            payload.get("total_cost_usd"),
        )
    if response_format == "codex-jsonl":
        events = [json.loads(line) for line in output.splitlines() if line.strip()]
        text = ""
        usage: dict[str, Any] = {}
        for event in events:
            item = event.get("item", {})
            if event.get("type") == "item.completed" and item.get("type") == "agent_message":
                text = item.get("text", text)
            if event.get("type") == "turn.completed":
                usage = event.get("usage", usage)
        return str(text).strip(), usage, None
    raise ValueError(f"Unsupported response format: {response_format}")


def invoke_runner(
    prompt: str,
    runner: dict[str, Any],
    *,
    retries: int,
    remaining_budget: float,
    allow_unmetered: bool,
) -> dict[str, Any]:
    """Run one provider invocation and return its response plus invocation metadata."""
    command = list(runner["command"])
    response_format = runner.get("response_format", "text")
    if response_format != "claude-json" and not allow_unmetered:
        raise RuntimeError(
            f"The {response_format!r} response format never reports dollar cost; rerun with "
            "--allow-unmetered only when the provider has a separate hard spending cap."
        )
    invocation = [*command]
    if runner.get("budget_flag"):
        invocation.extend([runner["budget_flag"], f"{remaining_budget:.4f}"])
    invocation.append(prompt)

    completed = None
    for attempt in range(retries + 1):
        completed = subprocess.run(
            invocation,
            check=False,
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        if completed.returncode == 0:
            break
        if attempt < retries:
            time.sleep(min(2**attempt, 5))
    assert completed is not None
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip()
        if completed.stdout.strip():
            try:
                parsed_text, _, _ = _parse_response(completed.stdout, response_format)
                detail = parsed_text or detail
            except (ValueError, json.JSONDecodeError):
                pass
        raise RuntimeError(
            f"Runner failed after {retries + 1} attempts "
            f"({shlex.join(invocation[:-1])}):\n{detail}"
        )
    text, usage, cost = _parse_response(completed.stdout, response_format)
    if cost is None and not allow_unmetered:
        raise RuntimeError(
            "Runner did not report dollar cost; rerun with --allow-unmetered only when "
            "the provider has a separate hard spending cap."
        )
    return {
        "response": text,
        "usage": usage,
        "cost_usd": cost,
        "invocation": {
            "command": invocation[:-1],
            "response_format": response_format,
            "remaining_budget_usd": remaining_budget,
        },
    }


def run_evaluations(args: argparse.Namespace) -> int:
    cases = load_cases(args.cases)
    errors = validate_cases(cases)
    if errors:
        raise ValueError("\n".join(errors))
    unknown = sorted(set(args.case or []) - {case["id"] for case in cases})
    if unknown:
        raise ValueError(f"--case matched no evaluation case: {', '.join(unknown)}")
    config = json.loads(args.runner_config.read_text(encoding="utf-8"))
    runner = config[args.runner]
    runner_config_digest = runner_config_sha256(runner)
    response_format = runner.get("response_format", "text")
    if response_format != "claude-json" and not args.allow_unmetered:
        raise RuntimeError(
            f"The {response_format!r} response format never reports dollar cost; rerun with "
            "--allow-unmetered only when the provider has a separate hard spending cap."
        )
    reported_cost = 0.0
    prior_rows = read_jsonl(args.output) if args.output.exists() else []
    completed_rows = {
        (row["case_id"], row["trial"], row["condition"], row["runner"]): row
        for row in prior_rows
        if isinstance(row.get("case_id"), str)
        and isinstance(row.get("trial"), int)
        and isinstance(row.get("condition"), str)
        and isinstance(row.get("runner"), str)
    }
    reported_cost = sum(
        float(row.get("cost_usd") or 0)
        for row in prior_rows
        if row.get("condition") == args.condition and row.get("runner") == args.runner
    )

    if args.budget_usd <= 0 or args.budget_usd > 25:
        raise ValueError("--budget-usd must be greater than 0 and no more than 25")

    skill_path = None if args.condition in {"baseline", "no_skill"} else args.condition_skill
    skill_snapshot = _load_skill_snapshot(skill_path)
    if args.condition not in {"baseline", "no_skill"} and skill_snapshot.data is None:
        raise ValueError(f"--condition-skill is required for the {args.condition} condition")
    skill = skill_snapshot.metadata()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("a", encoding="utf-8") as destination:
        for trial in range(1, args.trials + 1):
            for case in cases:
                if args.case and case["id"] not in args.case:
                    continue
                key = (case["id"], trial, args.condition, args.runner)
                task_sha256 = hashlib.sha256(case["prompt"].encode("utf-8")).hexdigest()
                if key in completed_rows:
                    _validate_resume_provenance(
                        completed_rows[key],
                        task_sha256=task_sha256,
                        skill=skill,
                        runner_config_digest=runner_config_digest,
                    )
                    print(f"skip completed {args.condition} trial {trial}: {case['id']}")
                    continue
                remaining = args.budget_usd - reported_cost
                if remaining <= 0:
                    print("Budget exhausted; stopping.", file=sys.stderr)
                    return 2
                prompt = _condition_prompt_from_snapshot(
                    case["prompt"], args.condition, skill_snapshot
                )
                result = invoke_runner(
                    prompt,
                    runner,
                    retries=args.retries,
                    remaining_budget=remaining,
                    allow_unmetered=args.allow_unmetered,
                )
                reported_cost += float(result["cost_usd"] or 0)
                row = {
                    "case_id": case["id"],
                    "trial": trial,
                    "condition": args.condition,
                    "runner": args.runner,
                    "response": result["response"],
                    "usage": result["usage"],
                    "cost_usd": result["cost_usd"],
                    "skill": skill,
                    "task_sha256": task_sha256,
                    "runner_config_sha256": runner_config_digest,
                }
                destination.write(json.dumps(row, ensure_ascii=False) + "\n")
                destination.flush()
                print(f"{args.condition} trial {trial}: {case['id']}")
    print(f"Reported cost: ${reported_cost:.4f}")
    return 0


def run_comparison(args: argparse.Namespace) -> int:
    conditions: list[tuple[str, Path | None]] = [
        ("base", args.base_skill),
        ("candidate", args.candidate_skill),
    ]
    if args.include_no_skill:
        conditions.append(("no_skill", None))
    for condition, skill in conditions:
        run_args = argparse.Namespace(
            **vars(args), condition=condition, condition_skill=skill
        )
        status = run_evaluations(run_args)
        if status:
            return status
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="Validate the case catalog")
    validate.add_argument("--cases", type=Path, default=DEFAULT_CASES)

    plan = subparsers.add_parser("plan", help="Print the paired run matrix as JSONL")
    plan.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    plan.add_argument("--trials", type=int, default=3)
    plan.add_argument("--include-comparator", action="store_true")

    score = subparsers.add_parser("score", help="Aggregate manually judged score rows")
    score.add_argument("scores", type=Path)

    run = subparsers.add_parser("run", help="Run one evaluation condition")
    run.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    run.add_argument("--runner-config", type=Path, default=ROOT / "evals" / "runners.example.json")
    run.add_argument("--runner", required=True)
    run.add_argument("--condition", choices=sorted(CONDITIONS), required=True)
    run.add_argument("--condition-skill", type=Path)
    run.add_argument("--case", action="append")
    run.add_argument("--trials", type=int, default=3)
    run.add_argument("--retries", type=int, default=2)
    run.add_argument("--budget-usd", type=float, default=25.0)
    run.add_argument("--allow-unmetered", action="store_true")
    run.add_argument("--output", type=Path, required=True)
    run.set_defaults(handler=run_evaluations)

    compare = subparsers.add_parser(
        "compare", help="Run base and candidate skills against identical evaluation cases"
    )
    compare.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    compare.add_argument(
        "--runner-config", type=Path, default=ROOT / "evals" / "runners.example.json"
    )
    compare.add_argument("--runner", required=True)
    compare.add_argument("--base-skill", type=Path, required=True)
    compare.add_argument("--candidate-skill", type=Path, required=True)
    compare.add_argument("--include-no-skill", action="store_true")
    compare.add_argument("--case", action="append")
    compare.add_argument("--trials", type=int, default=3)
    compare.add_argument("--retries", type=int, default=2)
    compare.add_argument("--budget-usd", type=float, default=25.0)
    compare.add_argument("--allow-unmetered", action="store_true")
    compare.add_argument("--output", type=Path, required=True)
    compare.set_defaults(handler=run_comparison)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if hasattr(args, "handler"):
        return args.handler(args)
    if args.command == "validate":
        errors = validate_cases(load_cases(args.cases))
        if errors:
            for error in errors:
                print(f"ERROR: {error}", file=sys.stderr)
            return 1
        print("Evaluation cases are valid.")
        return 0
    if args.command == "plan":
        cases = load_cases(args.cases)
        errors = validate_cases(cases)
        if errors:
            raise ValueError("\n".join(errors))
        conditions = ["baseline", "candidate"]
        if args.include_comparator:
            conditions.append("comparator")
        for trial in range(1, args.trials + 1):
            for case in cases:
                for condition in conditions:
                    print(json.dumps({"case_id": case["id"], "trial": trial, "condition": condition}))
        return 0
    if args.command == "score":
        print(json.dumps(summarize_scores(read_jsonl(args.scores)), indent=2))
        return 0
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
