#!/usr/bin/env python3
"""Run, blind, validate, and score the bounded two-scenario AUCI pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import run_evals


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCENARIOS = ROOT / "evals" / "auci_pilot" / "scenarios.json"
DEFAULT_CONTROLS = ROOT / "evals" / "auci_pilot" / "known_direction_controls.json"
DEFAULT_RUNNERS = ROOT / "evals" / "auci_pilot" / "runners.json"


SUBSTANCE_CLASSES = ("critical", "required", "optional")
SUBSTANCE_STATUSES = {"retained", "omitted", "contradicted"}
EXPECTED_SCENARIO_IDS = {"interruption-recovery", "rationale-caveat-preservation"}


def _nonempty_string(value: Any, message: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(message)
    return value


def _ids(items: Any, key: str, label: str) -> list[str]:
    if not isinstance(items, list):
        raise ValueError(f"{label} must be a list")
    identifiers: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError(f"{label} entries must be objects")
        identifiers.append(_nonempty_string(item.get(key), f"{label} ids must be non-empty strings"))
    return identifiers


def _require_exact_ids(
    expected: set[str], items: Any, key: str, label: str
) -> list[dict[str, Any]]:
    identifiers = _ids(items, key, label)
    if len(identifiers) != len(set(identifiers)) or set(identifiers) != expected:
        raise ValueError(f"{label} ids must match the scenario exactly")
    return items


def _has_skill_key(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            "skill" in str(key).lower() or _has_skill_key(child)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(_has_skill_key(child) for child in value)
    return False


def _validate_scenario(scenario: Any, index: int) -> dict[str, Any]:
    if not isinstance(scenario, dict):
        raise ValueError(f"Scenario {index} must be an object")
    scenario_id = _nonempty_string(scenario.get("id"), f"Scenario {index} id must be non-empty")
    turns = scenario.get("user_turns")
    if (
        not isinstance(turns, list)
        or len(turns) != 2
        or any(not isinstance(turn, str) or not turn.strip() for turn in turns)
    ):
        raise ValueError(f"Scenario {scenario_id} must contain exactly two non-empty user turns")
    if _has_skill_key(scenario):
        raise ValueError(f"Scenario {scenario_id} must not contain skill text fields")

    contract = scenario.get("task_contract")
    contract_ids = _ids(contract, "id", f"Scenario {scenario_id} task contract")
    if len(contract_ids) != len(set(contract_ids)):
        raise ValueError(f"Scenario {scenario_id} task contract ids must be unique")
    for fact in contract:
        _nonempty_string(
            fact.get("proposition"),
            f"Scenario {scenario_id} task contract propositions must be non-empty",
        )
        source_turn = fact.get("source_turn")
        source_excerpt = _nonempty_string(
            fact.get("source_excerpt"),
            f"Scenario {scenario_id} task contract source excerpts must be non-empty",
        )
        if type(source_turn) is not int or source_turn not in {1, 2}:
            raise ValueError(
                f"Scenario {scenario_id} task contract source turns must be 1 or 2"
            )
        if source_excerpt not in turns[source_turn - 1]:
            raise ValueError(
                f"Scenario {scenario_id} task contract source excerpt must occur "
                f"in user turn {source_turn}"
            )
    contract_id_set = set(contract_ids)

    opportunities = scenario.get("coordination_opportunities")
    opportunity_ids = _ids(
        opportunities, "id", f"Scenario {scenario_id} coordination opportunities"
    )
    if len(opportunity_ids) != len(set(opportunity_ids)):
        raise ValueError(f"Scenario {scenario_id} coordination opportunity ids must be unique")
    for opportunity in opportunities:
        for field in ("type", "severity", "description"):
            _nonempty_string(
                opportunity.get(field),
                f"Scenario {scenario_id} coordination opportunity {field} must be non-empty",
            )
        bases = opportunity.get("contract_basis_ids")
        if (
            not isinstance(bases, list)
            or not bases
            or any(not isinstance(value, str) for value in bases)
            or not set(bases) <= contract_id_set
        ):
            raise ValueError(
                f"Scenario {scenario_id} coordination opportunity contract basis ids "
                "must reference the task contract"
            )

    obligations = scenario.get("substance_obligations")
    if not isinstance(obligations, dict) or set(obligations) != set(SUBSTANCE_CLASSES):
        raise ValueError(
            f"Scenario {scenario_id} substance obligations must define critical, required, and optional"
        )
    all_obligation_ids: set[str] = set()
    for substance_class in SUBSTANCE_CLASSES:
        class_items = obligations[substance_class]
        class_ids = _ids(
            class_items,
            "id",
            f"Scenario {scenario_id} {substance_class} substance obligations",
        )
        if len(class_ids) != len(set(class_ids)) or all_obligation_ids & set(class_ids):
            raise ValueError(f"Scenario {scenario_id} substance obligation ids must be unique")
        if not class_items:
            raise ValueError(
                f"Scenario {scenario_id} {substance_class} substance obligations must not be empty"
            )
        all_obligation_ids.update(class_ids)
        for obligation in class_items:
            _nonempty_string(
                obligation.get("proposition"),
                f"Scenario {scenario_id} substance propositions must be non-empty",
            )
            bases = obligation.get("contract_basis_ids")
            if (
                not isinstance(bases, list)
                or not bases
                or any(not isinstance(value, str) for value in bases)
                or not set(bases) <= contract_id_set
            ):
                raise ValueError(
                    f"Scenario {scenario_id} substance contract basis ids must reference the task contract"
                )
    return scenario


def load_scenarios(path: Path) -> dict[str, dict[str, Any]]:
    """Load and behavior-validate the scenario catalog, keyed by scenario id."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: invalid JSON: {exc.msg}") from exc
    if not isinstance(payload, list):
        raise ValueError(f"{path}: scenario catalog must be a list")

    scenarios: dict[str, dict[str, Any]] = {}
    for index, raw_scenario in enumerate(payload, start=1):
        scenario = _validate_scenario(raw_scenario, index)
        if scenario["id"] in scenarios:
            raise ValueError(f"Duplicate scenario id: {scenario['id']}")
        scenarios[scenario["id"]] = scenario
    if set(scenarios) != EXPECTED_SCENARIO_IDS:
        raise ValueError(
            "Pilot scenario catalog must contain exactly interruption-recovery and "
            "rationale-caveat-preservation"
        )
    return scenarios


def _validate_gate(annotation: dict[str, Any], name: str) -> bool:
    gate = annotation.get(name)
    if not isinstance(gate, dict) or type(gate.get("passed")) is not bool:
        raise ValueError(f"{name}.passed must be boolean")
    _nonempty_string(gate.get("evidence"), "evidence must be a non-empty string")
    return gate["passed"]


def score_annotation(
    scenario: dict[str, Any], annotation: dict[str, Any]
) -> dict[str, Any]:
    """Validate one complete semantic annotation and calculate independent endpoints."""
    if not isinstance(annotation, dict):
        raise ValueError("annotation must be an object")
    if annotation.get("scenario_id") != scenario["id"]:
        raise ValueError("annotation scenario_id must match the scenario")

    expected_auci = {
        item["id"] for item in scenario["coordination_opportunities"]
    }
    coordination = _require_exact_ids(
        expected_auci,
        annotation.get("coordination"),
        "opportunity_id",
        "coordination opportunity",
    )
    auci_total = 0
    for item in coordination:
        if type(item.get("auci")) is not int or item["auci"] not in {0, 1}:
            raise ValueError("auci must be the integer 0 or 1")
        _nonempty_string(item.get("evidence"), "evidence must be a non-empty string")
        auci_total += item["auci"]

    substance_annotations = annotation.get("substance")
    if (
        not isinstance(substance_annotations, dict)
        or set(substance_annotations) != set(SUBSTANCE_CLASSES)
    ):
        raise ValueError("substance must define critical, required, and optional annotations")
    substance_scores: dict[str, dict[str, int]] = {}
    for substance_class in SUBSTANCE_CLASSES:
        expected = {
            item["id"]
            for item in scenario["substance_obligations"][substance_class]
        }
        items = _require_exact_ids(
            expected,
            substance_annotations[substance_class],
            "obligation_id",
            f"{substance_class} substance obligation",
        )
        retained = 0
        for item in items:
            if item.get("status") not in SUBSTANCE_STATUSES:
                raise ValueError(
                    "substance status must be retained, omitted, or contradicted"
                )
            _nonempty_string(item.get("evidence"), "evidence must be a non-empty string")
            retained += item["status"] == "retained"
        substance_scores[substance_class] = {
            "retained": retained,
            "total": len(items),
        }

    task_success = _validate_gate(annotation, "task_success")
    safety = _validate_gate(annotation, "safety")
    critical_substance = (
        substance_scores["critical"]["retained"]
        == substance_scores["critical"]["total"]
    )
    required_substance = (
        substance_scores["required"]["retained"]
        == substance_scores["required"]["total"]
    )
    gates = {
        "task_success": task_success,
        "safety": safety,
        "critical_substance": critical_substance,
        "required_substance": required_substance,
    }
    gates["eligible"] = all(gates.values())

    return {
        "scenario_id": scenario["id"],
        "auci_total": auci_total,
        "auci_opportunities": len(coordination),
        "coordination": coordination,
        "substance": substance_scores,
        "substance_details": substance_annotations,
        "gates": gates,
    }


def _validate_response_binding(annotation: dict[str, Any], response: str) -> None:
    expected_sha = hashlib.sha256(response.encode("utf-8")).hexdigest()
    if annotation.get("response_sha256") != expected_sha:
        raise ValueError("annotation response SHA-256 must match the reviewed response")
    spans = annotation.get("source_spans")
    if (
        not isinstance(spans, list)
        or not spans
        or any(not isinstance(span, str) or not span or span not in response for span in spans)
    ):
        raise ValueError("annotation source spans must be non-empty excerpts of the response")


def score_controls(
    scenarios: dict[str, dict[str, Any]], controls: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Validate and score concrete known-direction behavior fixtures."""
    if not isinstance(controls, list):
        raise ValueError("controls must be a list")
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for control in controls:
        if not isinstance(control, dict):
            raise ValueError("control entries must be objects")
        control_id = _nonempty_string(control.get("id"), "control id must be non-empty")
        if control_id in seen:
            raise ValueError(f"Duplicate control id: {control_id}")
        seen.add(control_id)
        _nonempty_string(
            control.get("assistant_response"),
            f"Control {control_id} assistant_response must be non-empty",
        )
        scenario_id = control.get("scenario_id")
        if scenario_id not in scenarios:
            raise ValueError(f"Control {control_id} references unknown scenario {scenario_id!r}")
        annotation = control.get("annotation")
        if not isinstance(annotation, dict):
            raise ValueError(f"Control {control_id} annotation must be an object")
        _validate_response_binding(annotation, control["assistant_response"])
        score = score_annotation(scenarios[scenario_id], annotation)
        results.append({"control_id": control_id, **score})
    return results


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read JSONL using the existing evaluation harness's strict loader."""
    return run_evals.read_jsonl(path)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _conversation_task(turns: list[dict[str, str]]) -> str:
    return (
        "Continue the conversation below. Respond only as the assistant to the "
        "final user turn.\n\n<conversation>\n"
        + json.dumps(turns, ensure_ascii=False, indent=2)
        + "\n</conversation>"
    )


def _selected_scenarios(
    scenarios: dict[str, dict[str, Any]], requested: list[str] | None
) -> list[dict[str, Any]]:
    if not requested:
        return list(scenarios.values())
    unknown = sorted(set(requested) - set(scenarios))
    if unknown:
        raise ValueError(f"--scenario matched no pilot scenario: {', '.join(unknown)}")
    requested_set = set(requested)
    return [scenario for scenario in scenarios.values() if scenario["id"] in requested_set]


def _validate_runner_script(runner: dict[str, Any]) -> None:
    script_value = runner.get("runner_script")
    expected_sha = runner.get("runner_script_sha256")
    if script_value is None and expected_sha is None:
        return
    if not isinstance(script_value, str) or not script_value or not isinstance(expected_sha, str):
        raise ValueError("runner_script and runner_script_sha256 must be declared together")
    script_path = Path(script_value)
    if not script_path.is_absolute():
        script_path = ROOT / script_path
    actual_sha = hashlib.sha256(script_path.read_bytes()).hexdigest()
    if actual_sha != expected_sha:
        raise ValueError(
            f"runner script SHA-256 mismatch for {script_path}: "
            f"expected {expected_sha}, got {actual_sha}"
        )


def run_pilot(args: argparse.Namespace) -> int:
    """Generate two assistant turns for base/candidate under one runner configuration."""
    scenarios = load_scenarios(args.scenarios)
    selected = _selected_scenarios(scenarios, args.scenario)
    if args.trials < 1:
        raise ValueError("--trials must be at least 1")
    if args.budget_usd <= 0 or args.budget_usd > 25:
        raise ValueError("--budget-usd must be greater than 0 and no more than 25")

    config = json.loads(args.runner_config.read_text(encoding="utf-8"))
    if args.runner not in config:
        raise ValueError(f"Unknown runner: {args.runner}")
    runner = config[args.runner]
    _validate_runner_script(runner)
    runner_config_digest = run_evals.runner_config_sha256(runner)
    conditions: list[tuple[str, run_evals._SkillSnapshot]] = [
        ("base", run_evals._load_skill_snapshot(args.base_skill)),
        ("candidate", run_evals._load_skill_snapshot(args.candidate_skill)),
    ]
    if args.include_no_skill:
        conditions.append(("no_skill", run_evals._load_skill_snapshot(None)))

    prior_rows = read_jsonl(args.output) if args.output.exists() else []
    prior_by_key = {
        (row.get("scenario_id"), row.get("trial"), row.get("condition"), row.get("runner")): row
        for row in prior_rows
    }
    reported_cost = {
        condition: sum(
            float(row.get("cost_usd") or 0)
            for row in prior_rows
            if row.get("condition") == condition and row.get("runner") == args.runner
        )
        for condition, _snapshot in conditions
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("a", encoding="utf-8") as destination:
        for condition, skill_snapshot in conditions:
            metadata = skill_snapshot.metadata()
            for trial in range(1, args.trials + 1):
                for scenario in selected:
                    key = (scenario["id"], trial, condition, args.runner)
                    scenario_canonical = json.dumps(
                        scenario,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    scenario_digest = hashlib.sha256(
                        scenario_canonical.encode("utf-8")
                    ).hexdigest()
                    if key in prior_by_key:
                        existing = prior_by_key[key]
                        if (
                            run_evals._resume_skill_identity(existing.get("skill"))
                            != run_evals._resume_skill_identity(metadata)
                            or existing.get("scenario_sha256") != scenario_digest
                            or existing.get("runner_config_sha256")
                            != runner_config_digest
                        ):
                            raise ValueError(
                                "Existing pilot trace provenance mismatch; use a new output "
                                "path for changed scenario, skill, or runner configuration: "
                                f"{scenario['id']}/trial {trial}/{condition}"
                            )
                        continue

                    conversation: list[dict[str, str]] = [
                        {"role": "user", "content": scenario["user_turns"][0]}
                    ]
                    assistant_turns: list[str] = []
                    provider_prompts: list[str] = []
                    turn_metadata: list[dict[str, Any]] = []
                    total_cost = 0.0
                    for turn_index in range(2):
                        task = _conversation_task(conversation)
                        provider_prompt = run_evals._condition_prompt_from_snapshot(
                            task, condition, skill_snapshot
                        )
                        remaining = args.budget_usd - reported_cost[condition]
                        if remaining <= 0:
                            print(
                                f"Budget exhausted for {condition}; stopping.",
                                file=sys.stderr,
                            )
                            return 2
                        result = run_evals.invoke_runner(
                            provider_prompt,
                            runner,
                            retries=args.retries,
                            remaining_budget=remaining,
                            allow_unmetered=args.allow_unmetered,
                        )
                        response = result["response"]
                        assistant_turns.append(response)
                        provider_prompts.append(provider_prompt)
                        conversation.append({"role": "assistant", "content": response})
                        turn_metadata.append(
                            {
                                "turn": turn_index + 1,
                                "usage": result["usage"],
                                "cost_usd": result["cost_usd"],
                                "invocation": result["invocation"],
                            }
                        )
                        cost = float(result["cost_usd"] or 0)
                        reported_cost[condition] += cost
                        total_cost += cost
                        if turn_index == 0:
                            conversation.append(
                                {"role": "user", "content": scenario["user_turns"][1]}
                            )

                    row = {
                        "scenario_id": scenario["id"],
                        "trial": trial,
                        "condition": condition,
                        "runner": args.runner,
                        "skill": metadata,
                        "scenario_sha256": scenario_digest,
                        "runner_config_sha256": runner_config_digest,
                        "user_turns": list(scenario["user_turns"]),
                        "assistant_turns": assistant_turns,
                        "provider_prompts": provider_prompts,
                        "turn_metadata": turn_metadata,
                        "cost_usd": total_cost or None,
                    }
                    destination.write(json.dumps(row, ensure_ascii=False) + "\n")
                    destination.flush()
                    print(f"{condition} trial {trial}: {scenario['id']}")
    return 0


def blind_traces(
    rows: list[dict[str, Any]], seed: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split raw traces into a shuffled review packet and a separate condition key."""
    shuffled = list(rows)
    random.Random(seed).shuffle(shuffled)
    packet: list[dict[str, Any]] = []
    key: list[dict[str, Any]] = []
    for index, row in enumerate(shuffled, start=1):
        sample_id = f"sample-{index:03d}"
        user_turns = row.get("user_turns")
        assistant_turns = row.get("assistant_turns")
        if (
            not isinstance(user_turns, list)
            or len(user_turns) != 2
            or not isinstance(assistant_turns, list)
            or len(assistant_turns) != 2
        ):
            raise ValueError("Every raw trace must contain exactly two user and assistant turns")
        packet.append(
            {
                "sample_id": sample_id,
                "scenario_id": row["scenario_id"],
                "trial": row["trial"],
                "conversation": [
                    {"role": "user", "content": user_turns[0]},
                    {"role": "assistant", "content": assistant_turns[0]},
                    {"role": "user", "content": user_turns[1]},
                    {"role": "assistant", "content": assistant_turns[1]},
                ],
            }
        )
        key.append(
            {
                "sample_id": sample_id,
                "scenario_id": row["scenario_id"],
                "trial": row["trial"],
                "condition": row["condition"],
                "runner": row["runner"],
                "runner_config_sha256": _nonempty_string(
                    row.get("runner_config_sha256"),
                    "raw trace runner_config_sha256 must be non-empty",
                ),
                "scenario_sha256": _nonempty_string(
                    row.get("scenario_sha256"),
                    "raw trace scenario_sha256 must be non-empty",
                ),
                "skill": row["skill"],
            }
        )
    return packet, key


def blind_controls(
    scenarios: dict[str, dict[str, Any]],
    controls: list[dict[str, Any]],
    seed: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Create control review samples without behavior labels or reference annotations."""
    shuffled = list(controls)
    random.Random(seed).shuffle(shuffled)
    packet: list[dict[str, Any]] = []
    key: list[dict[str, Any]] = []
    for index, control in enumerate(shuffled, start=1):
        control_id = _nonempty_string(control.get("id"), "control id must be non-empty")
        scenario_id = control.get("scenario_id")
        if scenario_id not in scenarios:
            raise ValueError(f"Control {control_id} references unknown scenario {scenario_id!r}")
        response = _nonempty_string(
            control.get("assistant_response"),
            f"Control {control_id} assistant_response must be non-empty",
        )
        sample_id = f"control-sample-{index:03d}"
        user_turns = scenarios[scenario_id]["user_turns"]
        packet.append(
            {
                "sample_id": sample_id,
                "scenario_id": scenario_id,
                "trial": 1,
                "conversation": [
                    {"role": "user", "content": user_turns[0]},
                    {
                        "role": "assistant",
                        "content": "Known-direction fixture: first-turn output is not under test.",
                    },
                    {"role": "user", "content": user_turns[1]},
                    {"role": "assistant", "content": response},
                ],
            }
        )
        key.append(
            {
                "sample_id": sample_id,
                "scenario_id": scenario_id,
                "control_id": control_id,
            }
        )
    return packet, key


def score_annotations(
    scenarios: dict[str, dict[str, Any]],
    annotations: list[dict[str, Any]],
    packet: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Score complete blind annotations while retaining opaque sample identifiers."""
    packet_by_id: dict[str, dict[str, Any]] = {}
    for item in packet:
        sample_id = _nonempty_string(
            item.get("sample_id"), "packet sample_id must be a non-empty string"
        )
        if sample_id in packet_by_id:
            raise ValueError(f"Duplicate packet sample_id: {sample_id}")
        packet_by_id[sample_id] = item
    scores: list[dict[str, Any]] = []
    seen: set[str] = set()
    for annotation in annotations:
        sample_id = _nonempty_string(
            annotation.get("sample_id"), "sample_id must be a non-empty string"
        )
        if sample_id in seen:
            raise ValueError(f"Duplicate sample_id: {sample_id}")
        seen.add(sample_id)
        scenario_id = annotation.get("scenario_id")
        if scenario_id not in scenarios:
            raise ValueError(f"Unknown annotation scenario_id: {scenario_id!r}")
        if sample_id not in packet_by_id:
            raise ValueError(f"Annotation sample_id is absent from blind packet: {sample_id}")
        packet_item = packet_by_id[sample_id]
        if packet_item.get("scenario_id") != scenario_id:
            raise ValueError("annotation scenario_id must match its blind packet sample")
        conversation = packet_item.get("conversation")
        if (
            not isinstance(conversation, list)
            or len(conversation) != 4
            or conversation[-1].get("role") != "assistant"
            or not isinstance(conversation[-1].get("content"), str)
        ):
            raise ValueError("blind packet sample must contain a complete two-turn conversation")
        _validate_response_binding(annotation, conversation[-1]["content"])
        scores.append(
            {"sample_id": sample_id, **score_annotation(scenarios[scenario_id], annotation)}
        )
    if seen != set(packet_by_id):
        raise ValueError("annotations must cover every blind packet sample exactly once")
    return scores


def unblind_scores(
    scores: list[dict[str, Any]], key: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Join complete blind scores to the separately held condition key."""
    score_by_id: dict[str, dict[str, Any]] = {}
    for score in scores:
        sample_id = _nonempty_string(
            score.get("sample_id"), "score sample_id must be a non-empty string"
        )
        if sample_id in score_by_id:
            raise ValueError(f"Duplicate score sample_id: {sample_id}")
        score_by_id[sample_id] = score
    key_by_id: dict[str, dict[str, Any]] = {}
    for entry in key:
        sample_id = _nonempty_string(
            entry.get("sample_id"), "key sample_id must be a non-empty string"
        )
        if sample_id in key_by_id:
            raise ValueError(f"Duplicate key sample_id: {sample_id}")
        key_by_id[sample_id] = entry
    if set(score_by_id) != set(key_by_id):
        raise ValueError("blind scores and key must contain exactly the same sample ids")
    _validate_paired_provenance(list(key_by_id.values()))

    rows: list[dict[str, Any]] = []
    for sample_id, score in score_by_id.items():
        entry = key_by_id[sample_id]
        if entry.get("scenario_id") != score.get("scenario_id"):
            raise ValueError("score scenario_id must match the blind key")
        rows.append(
            {
                **score,
                "condition": entry["condition"],
                "trial": entry["trial"],
                "runner": entry["runner"],
                "runner_config_sha256": entry["runner_config_sha256"],
                "scenario_sha256": entry["scenario_sha256"],
                "skill": entry["skill"],
            }
        )
    return rows


def _validate_paired_provenance(rows: list[dict[str, Any]]) -> None:
    """Reject mixed runners, duplicate cells, and provenance-unpaired conditions."""
    runner_configs: set[tuple[str, str]] = set()
    seen_cells: set[tuple[str, str, int]] = set()
    coverage: dict[str, Counter[tuple[str, int, str]]] = {}
    for row in rows:
        condition = _nonempty_string(
            row.get("condition"), "condition must be a non-empty string"
        )
        scenario_id = _nonempty_string(
            row.get("scenario_id"), "scenario_id must be a non-empty string"
        )
        trial = row.get("trial")
        if type(trial) is not int or trial < 1:
            raise ValueError("trial must be a positive integer")
        runner = _nonempty_string(
            row.get("runner"), "runner must be a non-empty string"
        )
        runner_config = _nonempty_string(
            row.get("runner_config_sha256"),
            "runner_config_sha256 must be a non-empty string",
        )
        scenario_digest = _nonempty_string(
            row.get("scenario_sha256"),
            "scenario_sha256 must be a non-empty string",
        )
        runner_configs.add((runner, runner_config))
        cell = (condition, scenario_id, trial)
        if cell in seen_cells:
            raise ValueError(
                "Duplicate condition/scenario/trial row in paired comparison: "
                f"{condition}/{scenario_id}/{trial}"
            )
        seen_cells.add(cell)
        coverage.setdefault(condition, Counter())[
            (scenario_id, trial, scenario_digest)
        ] += 1

    if len(runner_configs) != 1:
        raise ValueError("paired comparison must use one runner and runner configuration")
    if "base" not in coverage or "candidate" not in coverage:
        raise ValueError("comparison summary requires base and candidate conditions")
    base_coverage = coverage["base"]
    for condition, condition_coverage in coverage.items():
        if condition_coverage != base_coverage:
            raise ValueError(
                "all conditions must have identical provenance-bound coverage; "
                f"{condition} differs from base"
            )


def summarize_comparison(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize AUCI, substance, and gates separately for paired conditions."""
    _validate_paired_provenance(rows)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        condition = _nonempty_string(
            row.get("condition"), "condition must be a non-empty string"
        )
        grouped.setdefault(condition, []).append(row)
    conditions: dict[str, dict[str, Any]] = {}
    for condition, condition_rows in sorted(grouped.items()):
        skill_hashes = {
            row.get("skill", {}).get("sha256")
            if row.get("skill", {}).get("mode") != "no_skill"
            else "no_skill"
            for row in condition_rows
        }
        if len(skill_hashes) != 1:
            raise ValueError(f"{condition} rows contain multiple skill identities")
        substance = {
            substance_class: {
                "retained": sum(
                    row["substance"][substance_class]["retained"]
                    for row in condition_rows
                ),
                "total": sum(
                    row["substance"][substance_class]["total"]
                    for row in condition_rows
                ),
            }
            for substance_class in SUBSTANCE_CLASSES
        }
        gate_names = (
            "task_success",
            "safety",
            "critical_substance",
            "required_substance",
            "eligible",
        )
        gates_passed = {
            gate: sum(bool(row["gates"][gate]) for row in condition_rows)
            for gate in gate_names
        }
        scenarios: dict[str, dict[str, dict[str, Any]]] = {}
        for row in condition_rows:
            scenarios.setdefault(row["scenario_id"], {})[str(row["trial"])] = {
                "auci_total": row["auci_total"],
                "auci_opportunities": row["auci_opportunities"],
                "substance": row["substance"],
                "gates": row["gates"],
            }
        conditions[condition] = {
            "samples": len(condition_rows),
            "skill_sha256": next(iter(skill_hashes)),
            "auci_total": sum(row["auci_total"] for row in condition_rows),
            "auci_opportunities": sum(
                row["auci_opportunities"] for row in condition_rows
            ),
            "substance": substance,
            "gates_passed": gates_passed,
            "all_samples_eligible": gates_passed["eligible"] == len(condition_rows),
            "scenarios": scenarios,
        }
    return {
        "primary_comparison": ["base", "candidate"],
        "conditions": conditions,
    }


def unblind_control_scores(
    scores: list[dict[str, Any]], key: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Join independently adjudicated control scores to hidden control identities."""
    score_by_id = {row["sample_id"]: row for row in scores}
    key_by_id = {row["sample_id"]: row for row in key}
    if len(score_by_id) != len(scores) or len(key_by_id) != len(key):
        raise ValueError("control scores and key must contain unique sample ids")
    if set(score_by_id) != set(key_by_id):
        raise ValueError("control scores and key must contain exactly the same sample ids")
    rows: list[dict[str, Any]] = []
    for sample_id, score in score_by_id.items():
        entry = key_by_id[sample_id]
        if entry.get("scenario_id") != score.get("scenario_id"):
            raise ValueError("control score scenario_id must match the blind key")
        rows.append({**score, "control_id": entry["control_id"]})
    return rows


def validate_control_directions(results: list[dict[str, Any]]) -> None:
    by_id = {result["control_id"]: result for result in results}
    expected = {
        "state-blind",
        "over-scaffolded",
        "substance-stripped",
        "oracle-explicit-state",
        "early-failure",
    }
    if set(by_id) != expected:
        raise ValueError("Known-direction controls must contain exactly the five pilot controls")
    checks = [
        by_id["state-blind"]["auci_total"]
        > by_id["oracle-explicit-state"]["auci_total"],
        by_id["over-scaffolded"]["auci_total"] > 0,
        not by_id["substance-stripped"]["gates"]["required_substance"],
        by_id["early-failure"]["auci_total"]
        == by_id["early-failure"]["auci_opportunities"],
        not by_id["early-failure"]["gates"]["task_success"],
        not by_id["early-failure"]["gates"]["eligible"],
    ]
    if not all(checks):
        raise ValueError("Known-direction controls did not respond in the expected direction")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="Validate the two-scenario catalog")
    validate.add_argument("--scenarios", type=Path, default=DEFAULT_SCENARIOS)

    controls = subparsers.add_parser("controls", help="Score known-direction controls")
    controls.add_argument("--scenarios", type=Path, default=DEFAULT_SCENARIOS)
    controls.add_argument("--controls", type=Path, default=DEFAULT_CONTROLS)

    run = subparsers.add_parser("run", help="Run the two-turn paired pilot")
    run.add_argument("--scenarios", type=Path, default=DEFAULT_SCENARIOS)
    run.add_argument("--runner-config", type=Path, default=DEFAULT_RUNNERS)
    run.add_argument("--runner", required=True)
    run.add_argument("--base-skill", type=Path, required=True)
    run.add_argument("--candidate-skill", type=Path, required=True)
    run.add_argument("--include-no-skill", action="store_true")
    run.add_argument("--scenario", action="append")
    run.add_argument("--trials", type=int, default=1)
    run.add_argument("--retries", type=int, default=2)
    run.add_argument("--budget-usd", type=float, default=5.0)
    run.add_argument("--allow-unmetered", action="store_true")
    run.add_argument("--output", type=Path, required=True)
    run.set_defaults(handler=run_pilot)

    blind = subparsers.add_parser("blind", help="Create a review packet and separate key")
    blind.add_argument("--input", type=Path, required=True)
    blind.add_argument("--packet", type=Path, required=True)
    blind.add_argument("--key", type=Path, required=True)
    blind.add_argument("--seed", type=int, required=True)

    blind_controls_parser = subparsers.add_parser(
        "blind-controls", help="Blind known-direction behaviors for independent review"
    )
    blind_controls_parser.add_argument("--scenarios", type=Path, default=DEFAULT_SCENARIOS)
    blind_controls_parser.add_argument("--controls", type=Path, default=DEFAULT_CONTROLS)
    blind_controls_parser.add_argument("--packet", type=Path, required=True)
    blind_controls_parser.add_argument("--key", type=Path, required=True)
    blind_controls_parser.add_argument("--seed", type=int, required=True)

    score = subparsers.add_parser("score", help="Score complete semantic annotations")
    score.add_argument("--scenarios", type=Path, default=DEFAULT_SCENARIOS)
    score.add_argument("--annotations", type=Path, required=True)
    score.add_argument("--packet", type=Path, required=True)
    score.add_argument("--output", type=Path, required=True)

    summarize = subparsers.add_parser(
        "summarize", help="Join the blind key and summarize paired endpoints"
    )
    summarize.add_argument("--scores", type=Path, required=True)
    summarize.add_argument("--key", type=Path, required=True)
    summarize.add_argument("--output", type=Path, required=True)

    summarize_controls = subparsers.add_parser(
        "summarize-controls", help="Reveal and validate independently scored controls"
    )
    summarize_controls.add_argument("--scores", type=Path, required=True)
    summarize_controls.add_argument("--key", type=Path, required=True)
    summarize_controls.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if hasattr(args, "handler"):
        return args.handler(args)
    if args.command == "validate":
        scenarios = load_scenarios(args.scenarios)
        print(f"AUCI pilot scenarios are valid ({len(scenarios)} exactly).")
        return 0
    if args.command == "controls":
        scenarios = load_scenarios(args.scenarios)
        controls = json.loads(args.controls.read_text(encoding="utf-8"))
        results = score_controls(scenarios, controls)
        validate_control_directions(results)
        print(json.dumps(results, indent=2))
        return 0
    if args.command == "blind":
        packet, key = blind_traces(read_jsonl(args.input), args.seed)
        _write_jsonl(args.packet, packet)
        args.key.parent.mkdir(parents=True, exist_ok=True)
        args.key.write_text(json.dumps(key, indent=2) + "\n", encoding="utf-8")
        return 0
    if args.command == "blind-controls":
        scenarios = load_scenarios(args.scenarios)
        controls = json.loads(args.controls.read_text(encoding="utf-8"))
        packet, key = blind_controls(scenarios, controls, args.seed)
        _write_jsonl(args.packet, packet)
        args.key.parent.mkdir(parents=True, exist_ok=True)
        args.key.write_text(json.dumps(key, indent=2) + "\n", encoding="utf-8")
        return 0
    if args.command == "score":
        scores = score_annotations(
            load_scenarios(args.scenarios),
            read_jsonl(args.annotations),
            read_jsonl(args.packet),
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(scores, indent=2) + "\n", encoding="utf-8")
        return 0
    if args.command == "summarize":
        scores = json.loads(args.scores.read_text(encoding="utf-8"))
        key = json.loads(args.key.read_text(encoding="utf-8"))
        unblinded = unblind_scores(scores, key)
        payload = {"summary": summarize_comparison(unblinded), "samples": unblinded}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return 0
    if args.command == "summarize-controls":
        scores = json.loads(args.scores.read_text(encoding="utf-8"))
        key = json.loads(args.key.read_text(encoding="utf-8"))
        controls = unblind_control_scores(scores, key)
        validate_control_directions(controls)
        payload = {"known_direction_passed": True, "controls": controls}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return 0
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
