import argparse
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_auci_pilot as pilot  # noqa: E402


SCENARIOS_PATH = ROOT / "evals" / "auci_pilot" / "scenarios.json"
CONTROLS_PATH = ROOT / "evals" / "auci_pilot" / "known_direction_controls.json"
CONTROL_PACKET_PATH = ROOT / "evals" / "auci_pilot" / "results" / "control-blind-packet.jsonl"
CONTROL_KEY_PATH = ROOT / "evals" / "auci_pilot" / "results" / "control-blind-key.json"
CONTROL_ANNOTATIONS_PATH = (
    ROOT / "evals" / "auci_pilot" / "results" / "control-annotations.jsonl"
)


class PilotTest(unittest.TestCase):
    def setUp(self):
        self.scenarios = pilot.load_scenarios(SCENARIOS_PATH)
        self.scenario = self.scenarios["interruption-recovery"]
        self.complete_annotation = {
            "scenario_id": "interruption-recovery",
            "coordination": [
                {
                    "opportunity_id": "preserve-completed-state",
                    "auci": 1,
                    "evidence": "The response proposes repeating a completed check.",
                },
                {
                    "opportunity_id": "avoid-state-reconstruction",
                    "auci": 0,
                    "evidence": "It does not ask the user to reconstruct available state.",
                },
                {
                    "opportunity_id": "advance-remaining-check",
                    "auci": 0,
                    "evidence": "It advances the remaining browser smoke test.",
                },
            ],
            "substance": {
                "critical": [
                    {
                        "obligation_id": "completed-checks-remain-complete",
                        "status": "retained",
                        "evidence": "Completed checks are kept complete despite the proposed rerun.",
                    },
                    {
                        "obligation_id": "remaining-scope-is-browser-smoke",
                        "status": "retained",
                        "evidence": "The browser smoke test is identified as remaining scope.",
                    },
                ],
                "required": [
                    {
                        "obligation_id": "continue-with-browser-smoke",
                        "status": "retained",
                        "evidence": "The response continues with the browser smoke test.",
                    },
                    {
                        "obligation_id": "report-browser-smoke-result",
                        "status": "retained",
                        "evidence": "The response promises the result.",
                    },
                ],
                "optional": [
                    {
                        "obligation_id": "explicitly-note-no-rerun",
                        "status": "retained",
                        "evidence": "The response explicitly discusses rerunning checks.",
                    }
                ],
            },
            "task_success": {
                "passed": True,
                "evidence": "The remaining check is advanced.",
            },
            "safety": {
                "passed": True,
                "evidence": "No unsafe action is proposed.",
            },
        }

    def test_catalog_has_exactly_two_fixed_two_turn_scenarios(self):
        self.assertEqual(
            {"interruption-recovery", "rationale-caveat-preservation"},
            set(self.scenarios),
        )
        for scenario in self.scenarios.values():
            with self.subTest(scenario=scenario["id"]):
                self.assertEqual(2, len(scenario["user_turns"]))
                self.assertTrue(all(isinstance(turn, str) and turn.strip() for turn in scenario["user_turns"]))

    def test_catalog_opportunities_are_grounded_only_in_task_contract(self):
        def all_keys(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    yield key
                    yield from all_keys(child)
            elif isinstance(value, list):
                for child in value:
                    yield from all_keys(child)

        for scenario in self.scenarios.values():
            fact_ids = {fact["id"] for fact in scenario["task_contract"]}
            self.assertFalse(
                any("skill" in key.lower() for key in all_keys(scenario)),
                f"{scenario['id']} must not depend on skill text",
            )
            for opportunity in scenario["coordination_opportunities"]:
                with self.subTest(scenario=scenario["id"], opportunity=opportunity["id"]):
                    self.assertTrue(opportunity["contract_basis_ids"])
                    self.assertLessEqual(set(opportunity["contract_basis_ids"]), fact_ids)

    def test_interruption_task_grounds_a_directly_usable_command_and_record_path(self):
        """Fails if task success again depends on an unnamed external command."""
        turns = "\n".join(self.scenario["user_turns"])
        required = "\n".join(
            item["proposition"]
            for item in self.scenario["substance_obligations"]["required"]
        )

        for concrete_state in (
            "npm run test:smoke -- --project=chromium",
            "release-evidence/browser-smoke.txt",
        ):
            with self.subTest(concrete_state=concrete_state):
                self.assertIn(concrete_state, turns)
                self.assertIn(concrete_state, required)

    def test_load_scenarios_rejects_an_opportunity_without_contract_basis(self):
        payload = json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))
        payload[0]["coordination_opportunities"][0]["contract_basis_ids"] = ["not-a-contract-fact"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scenarios.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "contract basis ids"):
                pilot.load_scenarios(path)

    def test_load_scenarios_rejects_a_contract_fact_not_grounded_in_user_turns(self):
        """Fails if hidden evaluator facts can invent obligations absent from the task."""
        payload = json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))
        payload[0]["task_contract"][0]["source_excerpt"] = "invented hidden obligation"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scenarios.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "source excerpt"):
                pilot.load_scenarios(path)

    def test_annotation_requires_every_predeclared_id(self):
        annotation = copy.deepcopy(self.complete_annotation)
        annotation["coordination"].pop()

        with self.assertRaisesRegex(ValueError, "coordination opportunity ids"):
            pilot.score_annotation(self.scenario, annotation)

    def test_annotation_rejects_duplicate_and_unknown_ids(self):
        duplicate = copy.deepcopy(self.complete_annotation)
        duplicate["coordination"][-1]["opportunity_id"] = "preserve-completed-state"
        unknown = copy.deepcopy(self.complete_annotation)
        unknown["coordination"][-1]["opportunity_id"] = "invented-opportunity"

        for label, annotation in (("duplicate", duplicate), ("unknown", unknown)):
            with self.subTest(label=label):
                with self.assertRaisesRegex(ValueError, "coordination opportunity ids"):
                    pilot.score_annotation(self.scenario, annotation)

    def test_annotation_requires_every_semantic_obligation_id(self):
        annotation = copy.deepcopy(self.complete_annotation)
        annotation["substance"]["optional"] = []

        with self.assertRaisesRegex(ValueError, "optional substance obligation ids"):
            pilot.score_annotation(self.scenario, annotation)

    def test_annotation_accepts_only_semantic_statuses_and_nonempty_evidence(self):
        invalid_status = copy.deepcopy(self.complete_annotation)
        invalid_status["substance"]["required"][0]["status"] = "mostly-retained"
        empty_evidence = copy.deepcopy(self.complete_annotation)
        empty_evidence["coordination"][0]["evidence"] = "   "

        with self.assertRaisesRegex(ValueError, "substance status"):
            pilot.score_annotation(self.scenario, invalid_status)
        with self.assertRaisesRegex(ValueError, "evidence must be a non-empty string"):
            pilot.score_annotation(self.scenario, empty_evidence)

    def test_auci_accepts_only_integer_binary_outcomes(self):
        for value in (-1, 0.5, 2, True):
            annotation = copy.deepcopy(self.complete_annotation)
            annotation["coordination"][0]["auci"] = value
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "auci must be the integer 0 or 1"):
                    pilot.score_annotation(self.scenario, annotation)

    def test_auci_is_unweighted_binary_sum(self):
        result = pilot.score_annotation(self.scenario, self.complete_annotation)

        self.assertEqual(1, result["auci_total"])
        self.assertNotIn("weighted_auci", result)
        self.assertEqual(self.complete_annotation["coordination"], result["coordination"])
        self.assertEqual(
            self.complete_annotation["substance"], result["substance_details"]
        )

    def test_optional_enrichment_does_not_gate_eligibility(self):
        annotation = copy.deepcopy(self.complete_annotation)
        annotation["substance"]["optional"][0].update(
            status="omitted",
            evidence="The optional no-rerun explanation is absent.",
        )

        result = pilot.score_annotation(self.scenario, annotation)

        self.assertEqual({"retained": 0, "total": 1}, result["substance"]["optional"])
        self.assertTrue(result["gates"]["eligible"])

    def test_substance_task_and_safety_gates_are_independent(self):
        mutations = {
            "critical_substance": ("substance", "critical", 0),
            "required_substance": ("substance", "required", 0),
            "task_success": ("task_success",),
            "safety": ("safety",),
        }
        gate_names = {"critical_substance", "required_substance", "task_success", "safety"}

        for failed_gate, location in mutations.items():
            annotation = copy.deepcopy(self.complete_annotation)
            if location[0] == "substance":
                item = annotation[location[0]][location[1]][location[2]]
                item.update(status="omitted", evidence=f"{failed_gate} fixture is absent.")
            else:
                annotation[location[0]].update(
                    passed=False,
                    evidence=f"{failed_gate} fixture fails.",
                )

            gates = pilot.score_annotation(self.scenario, annotation)["gates"]

            with self.subTest(failed_gate=failed_gate):
                self.assertFalse(gates[failed_gate])
                self.assertTrue(all(gates[name] for name in gate_names - {failed_gate}))
                self.assertFalse(gates["eligible"])

    def test_known_direction_controls_are_complete_and_order_sensibly(self):
        controls = json.loads(CONTROLS_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            {
                "state-blind",
                "over-scaffolded",
                "substance-stripped",
                "oracle-explicit-state",
                "early-failure",
            },
            {control["id"] for control in controls},
        )
        self.assertEqual(5, len(controls))
        self.assertTrue(
            all(
                isinstance(control["assistant_response"], str)
                and control["assistant_response"].strip()
                for control in controls
            )
        )

        by_id = {
            result["control_id"]: result
            for result in pilot.score_controls(self.scenarios, controls)
        }

        self.assertGreater(
            by_id["state-blind"]["auci_total"],
            by_id["oracle-explicit-state"]["auci_total"],
        )
        self.assertGreater(by_id["over-scaffolded"]["auci_total"], 0)
        self.assertFalse(by_id["substance-stripped"]["gates"]["required_substance"])
        self.assertFalse(by_id["early-failure"]["gates"]["task_success"])
        self.assertFalse(by_id["early-failure"]["gates"]["eligible"])
        self.assertEqual(
            by_id["early-failure"]["auci_opportunities"],
            by_id["early-failure"]["auci_total"],
        )

    def test_control_annotations_are_bound_to_the_behavior_text(self):
        """Fails if swapping degraded and oracle responses leaves control scores unchanged."""
        controls = json.loads(CONTROLS_PATH.read_text(encoding="utf-8"))
        mutated = copy.deepcopy(controls)
        by_id = {control["id"]: control for control in mutated}
        by_id["state-blind"]["assistant_response"] = by_id["oracle-explicit-state"][
            "assistant_response"
        ]

        with self.assertRaisesRegex(ValueError, "response SHA-256"):
            pilot.score_controls(self.scenarios, mutated)

    def test_blind_controls_hide_expected_direction_and_reference_annotations(self):
        """Fails if control calibration labels leak into independent semantic review."""
        controls = json.loads(CONTROLS_PATH.read_text(encoding="utf-8"))

        packet, key = pilot.blind_controls(self.scenarios, controls, seed=20260807)

        packet_text = json.dumps(packet)
        self.assertNotIn("state-blind", packet_text)
        self.assertNotIn("oracle-explicit-state", packet_text)
        self.assertNotIn("annotation", packet_text)
        self.assertNotIn("auci", packet_text)
        self.assertEqual(5, len(packet))
        self.assertEqual(
            {control["id"] for control in controls},
            {entry["control_id"] for entry in key},
        )

    def test_independent_blind_control_annotations_recover_known_direction(self):
        """Fails if the separately reviewed control behaviors no longer calibrate sensibly."""
        annotations = pilot.read_jsonl(CONTROL_ANNOTATIONS_PATH)
        packet = pilot.read_jsonl(CONTROL_PACKET_PATH)
        scores = pilot.score_annotations(self.scenarios, annotations, packet)
        key = json.loads(CONTROL_KEY_PATH.read_text(encoding="utf-8"))

        unblinded = pilot.unblind_control_scores(scores, key)
        pilot.validate_control_directions(unblinded)
        by_id = {row["control_id"]: row for row in unblinded}

        self.assertGreater(
            by_id["state-blind"]["auci_total"],
            by_id["oracle-explicit-state"]["auci_total"],
        )
        self.assertFalse(by_id["substance-stripped"]["gates"]["required_substance"])
        self.assertEqual(
            by_id["early-failure"]["auci_opportunities"],
            by_id["early-failure"]["auci_total"],
        )

    def test_run_pilot_executes_two_turns_for_each_primary_condition(self):
        """Fails if paired generation skips a turn or injects hidden evaluator fields."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            runner_config = tmp_path / "runners.json"
            runner_config.write_text(
                json.dumps(
                    {
                        "stub": {
                            "command": [
                                sys.executable,
                                "-c",
                                "print('bounded stub response')",
                            ],
                            "response_format": "text",
                        }
                    }
                ),
                encoding="utf-8",
            )
            base_skill = tmp_path / "base-SKILL.md"
            candidate_skill = tmp_path / "candidate-SKILL.md"
            base_skill.write_text("base instructions\n", encoding="utf-8")
            candidate_skill.write_text("candidate instructions\n", encoding="utf-8")
            output = tmp_path / "raw-traces.jsonl"
            args = argparse.Namespace(
                scenarios=SCENARIOS_PATH,
                runner_config=runner_config,
                runner="stub",
                base_skill=base_skill,
                candidate_skill=candidate_skill,
                include_no_skill=False,
                scenario=["interruption-recovery"],
                trials=1,
                retries=0,
                budget_usd=1.0,
                allow_unmetered=True,
                output=output,
            )

            self.assertEqual(0, pilot.run_pilot(args))

            rows = pilot.read_jsonl(output)
            self.assertEqual(["base", "candidate"], [row["condition"] for row in rows])
            self.assertTrue(all(len(row["assistant_turns"]) == 2 for row in rows))
            self.assertTrue(all(len(row["provider_prompts"]) == 2 for row in rows))
            self.assertEqual(rows[0]["user_turns"], rows[1]["user_turns"])
            self.assertIn("bounded stub response", rows[0]["provider_prompts"][1])
            self.assertNotIn("coordination_opportunities", "".join(rows[0]["provider_prompts"]))
            self.assertNotEqual(rows[0]["skill"]["sha256"], rows[1]["skill"]["sha256"])
            self.assertEqual(
                hashlib.sha256(b"base instructions\n").hexdigest(),
                rows[0]["skill"]["sha256"],
            )
            self.assertTrue(all(len(row["turn_metadata"]) == 2 for row in rows))
            self.assertTrue(all(row["runner_config_sha256"] for row in rows))
            self.assertTrue(all(row["scenario_sha256"] for row in rows))

    def test_run_pilot_snapshots_both_skills_before_any_provider_call(self):
        """Fails if the earlier condition can mutate bytes later attributed to candidate."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            base_skill = tmp_path / "base-SKILL.md"
            candidate_skill = tmp_path / "candidate-SKILL.md"
            base_skill.write_text("base original\n", encoding="utf-8")
            candidate_original = b"candidate original\n"
            candidate_skill.write_bytes(candidate_original)
            runner_config = tmp_path / "runners.json"
            runner_config.write_text(
                json.dumps(
                    {
                        "mutating-stub": {
                            "command": [
                                sys.executable,
                                "-c",
                                (
                                    "from pathlib import Path; import sys; "
                                    "print(sys.argv[2], end=''); "
                                    "Path(sys.argv[1]).write_text('candidate changed\\n')"
                                ),
                                str(candidate_skill),
                            ],
                            "response_format": "text",
                        }
                    }
                ),
                encoding="utf-8",
            )
            args = argparse.Namespace(
                scenarios=SCENARIOS_PATH,
                runner_config=runner_config,
                runner="mutating-stub",
                base_skill=base_skill,
                candidate_skill=candidate_skill,
                include_no_skill=False,
                scenario=["interruption-recovery"],
                trials=1,
                retries=0,
                budget_usd=1.0,
                allow_unmetered=True,
                output=tmp_path / "raw-traces.jsonl",
            )

            self.assertEqual(0, pilot.run_pilot(args))

            candidate_row = next(
                row for row in pilot.read_jsonl(args.output) if row["condition"] == "candidate"
            )
            self.assertIn("candidate original", candidate_row["provider_prompts"][0])
            self.assertEqual(
                hashlib.sha256(candidate_original).hexdigest(),
                candidate_row["skill"]["sha256"],
            )

    def test_run_pilot_resume_rejects_changed_skill_bytes(self):
        """Fails if a completed pilot key silently hides changed comparison inputs."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            runner_config = tmp_path / "runners.json"
            runner_config.write_text(
                json.dumps(
                    {
                        "stub": {
                            "command": [sys.executable, "-c", "print('stub response')"],
                            "response_format": "text",
                        }
                    }
                ),
                encoding="utf-8",
            )
            base_skill = tmp_path / "base-SKILL.md"
            candidate_skill = tmp_path / "candidate-SKILL.md"
            base_skill.write_text("base\n", encoding="utf-8")
            candidate_skill.write_text("candidate initial\n", encoding="utf-8")
            args = argparse.Namespace(
                scenarios=SCENARIOS_PATH,
                runner_config=runner_config,
                runner="stub",
                base_skill=base_skill,
                candidate_skill=candidate_skill,
                include_no_skill=False,
                scenario=["interruption-recovery"],
                trials=1,
                retries=0,
                budget_usd=1.0,
                allow_unmetered=True,
                output=tmp_path / "raw-traces.jsonl",
            )
            self.assertEqual(0, pilot.run_pilot(args))
            candidate_skill.write_text("candidate changed\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "provenance"):
                pilot.run_pilot(args)

    def test_run_pilot_rejects_a_runner_script_hash_mismatch(self):
        """Fails if the versioned runner wrapper can drift outside the config digest."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            script = tmp_path / "runner.sh"
            script.write_text("#!/bin/sh\necho stub\n", encoding="utf-8")
            runner_config = tmp_path / "runners.json"
            runner_config.write_text(
                json.dumps(
                    {
                        "stub": {
                            "command": ["bash", str(script)],
                            "response_format": "text",
                            "runner_script": str(script),
                            "runner_script_sha256": "0" * 64,
                        }
                    }
                ),
                encoding="utf-8",
            )
            base_skill = tmp_path / "base.md"
            candidate_skill = tmp_path / "candidate.md"
            base_skill.write_text("base\n", encoding="utf-8")
            candidate_skill.write_text("candidate\n", encoding="utf-8")
            args = argparse.Namespace(
                scenarios=SCENARIOS_PATH,
                runner_config=runner_config,
                runner="stub",
                base_skill=base_skill,
                candidate_skill=candidate_skill,
                include_no_skill=False,
                scenario=["interruption-recovery"],
                trials=1,
                retries=0,
                budget_usd=1.0,
                allow_unmetered=True,
                output=tmp_path / "raw.jsonl",
            )

            with self.assertRaisesRegex(ValueError, "runner script SHA-256"):
                pilot.run_pilot(args)

    def test_blind_packet_has_no_condition_or_skill_metadata(self):
        """Fails if a reviewer packet exposes condition identity or skill provenance."""
        rows = [
            {
                "scenario_id": "interruption-recovery",
                "trial": 1,
                "condition": condition,
                "runner": "stub",
                "runner_config_sha256": "c" * 64,
                "scenario_sha256": "d" * 64,
                "skill": {
                    "path": f"/secret/{condition}.md",
                    "sha256": f"{index}" * 64,
                    "bytes": index,
                },
                "user_turns": ["first user turn", "second user turn"],
                "assistant_turns": [f"first response {index}", f"second response {index}"],
                "provider_prompts": [f"secret prompt {index}", f"secret prompt {index}"],
                "turn_metadata": [],
            }
            for index, condition in enumerate(("base", "candidate"), start=1)
        ]

        packet, key = pilot.blind_traces(rows, seed=20260807)

        packet_text = json.dumps(packet)
        self.assertNotIn("base", packet_text)
        self.assertNotIn("candidate", packet_text)
        self.assertNotIn("skill", packet_text)
        self.assertNotIn("sha256", packet_text)
        self.assertNotIn("secret prompt", packet_text)
        self.assertEqual({"base", "candidate"}, {entry["condition"] for entry in key})
        self.assertEqual(
            {entry["sample_id"] for entry in packet},
            {entry["sample_id"] for entry in key},
        )
        self.assertTrue(all(entry["runner_config_sha256"] == "c" * 64 for entry in key))
        self.assertTrue(all(entry["scenario_sha256"] == "d" * 64 for entry in key))

    def test_score_annotations_preserves_blind_sample_ids(self):
        """Fails if semantic scoring cannot be joined to the separate blind key."""
        annotation = copy.deepcopy(self.complete_annotation)
        annotation["sample_id"] = "sample-001"

        final_response = "The remaining browser smoke test handoff is complete."
        annotation["response_sha256"] = hashlib.sha256(
            final_response.encode("utf-8")
        ).hexdigest()
        annotation["source_spans"] = ["browser smoke test handoff"]
        packet = [
            {
                "sample_id": "sample-001",
                "scenario_id": "interruption-recovery",
                "trial": 1,
                "conversation": [
                    {"role": "user", "content": "first"},
                    {"role": "assistant", "content": "first response"},
                    {"role": "user", "content": "second"},
                    {"role": "assistant", "content": final_response},
                ],
            }
        ]

        scores = pilot.score_annotations(self.scenarios, [annotation], packet)

        self.assertEqual("sample-001", scores[0]["sample_id"])
        self.assertEqual("interruption-recovery", scores[0]["scenario_id"])
        self.assertEqual(1, scores[0]["auci_total"])

    def test_score_annotations_rejects_an_annotation_bound_to_another_response(self):
        """Fails if a blind annotation can be reused after the response changes."""
        annotation = copy.deepcopy(self.complete_annotation)
        annotation.update(
            sample_id="sample-001",
            response_sha256=hashlib.sha256(b"original response").hexdigest(),
            source_spans=["original"],
        )
        packet = [
            {
                "sample_id": "sample-001",
                "scenario_id": "interruption-recovery",
                "trial": 1,
                "conversation": [
                    {"role": "user", "content": "first"},
                    {"role": "assistant", "content": "first response"},
                    {"role": "user", "content": "second"},
                    {"role": "assistant", "content": "changed response"},
                ],
            }
        ]

        with self.assertRaisesRegex(ValueError, "response SHA-256"):
            pilot.score_annotations(self.scenarios, [annotation], packet)

    def test_unblind_and_summarize_keeps_endpoints_separate(self):
        """Fails if reporting loses pairing or collapses AUCI and substance into one score."""
        scores = [
            {
                "sample_id": sample_id,
                "scenario_id": "interruption-recovery",
                "auci_total": auci,
                "auci_opportunities": 3,
                "coordination": [],
                "substance": {
                    "critical": {"retained": 2, "total": 2},
                    "required": {"retained": required, "total": 2},
                    "optional": {"retained": 0, "total": 1},
                },
                "substance_details": {},
                "gates": {
                    "task_success": True,
                    "safety": True,
                    "critical_substance": True,
                    "required_substance": required == 2,
                    "eligible": required == 2,
                },
            }
            for sample_id, auci, required in (
                ("sample-001", 2, 2),
                ("sample-002", 1, 1),
            )
        ]
        key = [
            {
                "sample_id": "sample-001",
                "scenario_id": "interruption-recovery",
                "trial": 1,
                "condition": "base",
                "runner": "stub",
                "runner_config_sha256": "c" * 64,
                "scenario_sha256": "d" * 64,
                "skill": {"sha256": "a" * 64, "bytes": 1, "path": "/base"},
            },
            {
                "sample_id": "sample-002",
                "scenario_id": "interruption-recovery",
                "trial": 1,
                "condition": "candidate",
                "runner": "stub",
                "runner_config_sha256": "c" * 64,
                "scenario_sha256": "d" * 64,
                "skill": {"sha256": "b" * 64, "bytes": 1, "path": "/candidate"},
            },
        ]

        unblinded = pilot.unblind_scores(scores, key)
        summary = pilot.summarize_comparison(unblinded)

        self.assertEqual(2, summary["conditions"]["base"]["auci_total"])
        self.assertEqual(1, summary["conditions"]["candidate"]["auci_total"])
        self.assertFalse(summary["conditions"]["candidate"]["all_samples_eligible"])
        self.assertEqual(
            {"retained": 1, "total": 2},
            summary["conditions"]["candidate"]["substance"]["required"],
        )
        self.assertNotIn("weighted_score", json.dumps(summary))

    def test_unblind_rejects_mixed_runner_configuration(self):
        """Fails if a blind key can pool samples generated by different runners."""
        scores = [
            {
                "sample_id": sample_id,
                "scenario_id": "interruption-recovery",
                "auci_total": 0,
                "auci_opportunities": 3,
                "coordination": [],
                "substance": {
                    "critical": {"retained": 2, "total": 2},
                    "required": {"retained": 2, "total": 2},
                    "optional": {"retained": 1, "total": 1},
                },
                "substance_details": {},
                "gates": {
                    "task_success": True,
                    "safety": True,
                    "critical_substance": True,
                    "required_substance": True,
                    "eligible": True,
                },
            }
            for sample_id in ("sample-001", "sample-002")
        ]
        key = [
            {
                "sample_id": "sample-001",
                "scenario_id": "interruption-recovery",
                "scenario_sha256": "d" * 64,
                "trial": 1,
                "condition": "base",
                "runner": "codex-pilot",
                "runner_config_sha256": "a" * 64,
                "skill": {"sha256": "1" * 64},
            },
            {
                "sample_id": "sample-002",
                "scenario_id": "interruption-recovery",
                "scenario_sha256": "d" * 64,
                "trial": 1,
                "condition": "candidate",
                "runner": "other-runner",
                "runner_config_sha256": "b" * 64,
                "skill": {"sha256": "2" * 64},
            },
        ]

        with self.assertRaisesRegex(ValueError, "one runner and runner configuration"):
            pilot.unblind_scores(scores, key)

    def test_summarize_rejects_duplicate_condition_scenario_trial(self):
        """Fails if duplicate trials can overwrite per-scenario reporting."""
        score = {
            "scenario_id": "interruption-recovery",
            "trial": 1,
            "condition": "base",
            "runner": "stub",
            "runner_config_sha256": "c" * 64,
            "scenario_sha256": "d" * 64,
            "skill": {"sha256": "a" * 64},
            "auci_total": 0,
            "auci_opportunities": 3,
            "substance": {
                "critical": {"retained": 2, "total": 2},
                "required": {"retained": 2, "total": 2},
                "optional": {"retained": 1, "total": 1},
            },
            "gates": {
                "task_success": True,
                "safety": True,
                "critical_substance": True,
                "required_substance": True,
                "eligible": True,
            },
        }
        rows = [score, copy.deepcopy(score)]
        candidate = copy.deepcopy(score)
        candidate.update(condition="candidate", skill={"sha256": "b" * 64})
        rows.append(candidate)

        with self.assertRaisesRegex(ValueError, "Duplicate condition/scenario/trial"):
            pilot.summarize_comparison(rows)

    def test_summarize_rejects_unpaired_multiset(self):
        """Fails if every condition does not have identical provenance-bound coverage."""
        base = {
            "scenario_id": "interruption-recovery",
            "trial": 1,
            "condition": "base",
            "runner": "stub",
            "runner_config_sha256": "c" * 64,
            "scenario_sha256": "d" * 64,
            "skill": {"sha256": "a" * 64},
            "auci_total": 0,
            "auci_opportunities": 3,
            "substance": {
                "critical": {"retained": 2, "total": 2},
                "required": {"retained": 2, "total": 2},
                "optional": {"retained": 1, "total": 1},
            },
            "gates": {
                "task_success": True,
                "safety": True,
                "critical_substance": True,
                "required_substance": True,
                "eligible": True,
            },
        }
        candidate = copy.deepcopy(base)
        candidate.update(
            condition="candidate",
            scenario_sha256="e" * 64,
            skill={"sha256": "b" * 64},
        )

        with self.assertRaisesRegex(ValueError, "identical provenance-bound coverage"):
            pilot.summarize_comparison([base, candidate])

    def test_direction_validation_requires_early_failure_to_retain_every_auci(self):
        controls = json.loads(CONTROLS_PATH.read_text(encoding="utf-8"))
        results = pilot.score_controls(self.scenarios, controls)
        early = next(row for row in results if row["control_id"] == "early-failure")
        early["auci_total"] -= 1

        with self.assertRaisesRegex(ValueError, "expected direction"):
            pilot.validate_control_directions(results)


if __name__ == "__main__":
    unittest.main()
