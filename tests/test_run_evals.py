import argparse
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_evals  # noqa: E402


class EvaluationHarnessTest(unittest.TestCase):
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
        """Fails if comparison omits a condition or loses its exact provenance."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cases = tmp_path / "cases.jsonl"
            task = "Reply with the task exactly."
            cases.write_text(
                json.dumps(
                    {
                        "id": "one-case",
                        "category": "fixture",
                        "prompt": task,
                        "risk": "low",
                        "criteria": ["Returns the supplied task."],
                    }
                )
                + "\n"
            )
            base_skill = tmp_path / "base-SKILL.md"
            candidate_skill = tmp_path / "candidate-SKILL.md"
            base_skill.write_bytes(b"base instructions\n")
            candidate_skill.write_bytes(b"candidate instructions\n")
            runner_config = tmp_path / "runners.json"
            runner_config.write_text(
                json.dumps(
                    {
                        "stub": {
                            "command": ["sh", "-c", 'printf "%s" "$1"', "stub"],
                            "response_format": "text",
                        }
                    }
                )
            )
            output = tmp_path / "responses.jsonl"
            args = argparse.Namespace(
                cases=cases,
                runner_config=runner_config,
                runner="stub",
                base_skill=base_skill,
                candidate_skill=candidate_skill,
                include_no_skill=True,
                case=None,
                trials=1,
                retries=0,
                budget_usd=1.0,
                allow_unmetered=True,
                output=output,
            )

            self.assertEqual(0, run_evals.run_comparison(args))

            rows = run_evals.read_jsonl(output)
            self.assertEqual(["base", "candidate", "no_skill"], [row["condition"] for row in rows])
            self.assertNotEqual(rows[0]["skill"]["sha256"], rows[1]["skill"]["sha256"])
            self.assertEqual({"mode": "no_skill"}, rows[2]["skill"])
            self.assertIn("base instructions", rows[0]["response"])
            self.assertNotIn("candidate instructions", rows[0]["response"])
            self.assertIn("candidate instructions", rows[1]["response"])
            self.assertNotIn("base instructions", rows[1]["response"])
            self.assertEqual(task, rows[2]["response"])
            self.assertEqual(hashlib.sha256(task.encode("utf-8")).hexdigest(), rows[0]["task_sha256"])
            self.assertEqual(
                hashlib.sha256(
                    json.dumps(
                        {
                            "command": ["sh", "-c", 'printf "%s" "$1"', "stub"],
                            "response_format": "text",
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
                rows[0]["runner_config_sha256"],
            )

    def test_skill_snapshot_binds_prompt_and_metadata_to_same_bytes(self):
        """Fails if a runner can change a skill between prompt injection and row metadata."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cases = tmp_path / "cases.jsonl"
            cases.write_text(
                json.dumps(
                    {
                        "id": "one-case",
                        "category": "fixture",
                        "prompt": "Do the task.",
                        "risk": "low",
                        "criteria": ["Returns the supplied task."],
                    }
                )
                + "\n"
            )
            skill = tmp_path / "SKILL.md"
            original = b"original instructions\n"
            skill.write_bytes(original)
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
                                    "Path(sys.argv[1]).write_bytes(b'changed instructions\\n')"
                                ),
                                str(skill),
                            ],
                            "response_format": "text",
                        }
                    }
                )
            )
            args = argparse.Namespace(
                cases=cases,
                runner_config=runner_config,
                runner="mutating-stub",
                condition="candidate",
                condition_skill=skill,
                case=None,
                trials=1,
                retries=0,
                budget_usd=1.0,
                allow_unmetered=True,
                output=tmp_path / "responses.jsonl",
            )

            self.assertEqual(0, run_evals.run_evaluations(args))

            row = run_evals.read_jsonl(args.output)[0]
            self.assertIn("original instructions", row["response"])
            self.assertEqual(hashlib.sha256(original).hexdigest(), row["skill"]["sha256"])

    def test_resume_rejects_changed_execution_provenance(self):
        """Fails if completed rows hide a changed task, skill, or runner configuration."""
        for changed in ("skill", "task", "runner"):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                cases = tmp_path / "cases.jsonl"
                skill = tmp_path / "SKILL.md"
                runner_config = tmp_path / "runners.json"
                cases.write_text(
                    json.dumps(
                        {
                            "id": "one-case",
                            "category": "fixture",
                            "prompt": "Initial task.",
                            "risk": "low",
                            "criteria": ["Returns the supplied task."],
                        }
                    )
                    + "\n"
                )
                skill.write_text("Initial skill.\n")
                runner_config.write_text(
                    json.dumps(
                        {
                            "stub": {
                                "command": ["sh", "-c", 'printf "%s" "$1"', "stub"],
                                "response_format": "text",
                            }
                        }
                    )
                )
                args = argparse.Namespace(
                    cases=cases,
                    runner_config=runner_config,
                    runner="stub",
                    condition="candidate",
                    condition_skill=skill,
                    case=None,
                    trials=1,
                    retries=0,
                    budget_usd=1.0,
                    allow_unmetered=True,
                    output=tmp_path / "responses.jsonl",
                )
                self.assertEqual(0, run_evals.run_evaluations(args))

                if changed == "skill":
                    skill.write_text("Changed skill.\n")
                elif changed == "task":
                    cases.write_text(
                        json.dumps(
                            {
                                "id": "one-case",
                                "category": "fixture",
                                "prompt": "Changed task.",
                                "risk": "low",
                                "criteria": ["Returns the supplied task."],
                            }
                        )
                        + "\n"
                    )
                else:
                    runner_config.write_text(
                        json.dumps(
                            {
                                "stub": {
                                    "command": ["sh", "-c", 'printf "changed: %s" "$1"', "stub"],
                                    "response_format": "text",
                                }
                            }
                        )
                    )

                with self.assertRaisesRegex(ValueError, "provenance"):
                    run_evals.run_evaluations(args)

    def test_resume_skips_matching_execution_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cases = tmp_path / "cases.jsonl"
            cases.write_text(
                json.dumps(
                    {
                        "id": "one-case",
                        "category": "fixture",
                        "prompt": "Do the task.",
                        "risk": "low",
                        "criteria": ["Returns the supplied task."],
                    }
                )
                + "\n"
            )
            skill = tmp_path / "SKILL.md"
            skill.write_text("Skill.\n")
            runner_config = tmp_path / "runners.json"
            runner_config.write_text(
                json.dumps(
                    {
                        "stub": {
                            "command": ["sh", "-c", 'printf "%s" "$1"', "stub"],
                            "response_format": "text",
                        }
                    }
                )
            )
            args = argparse.Namespace(
                cases=cases,
                runner_config=runner_config,
                runner="stub",
                condition="candidate",
                condition_skill=skill,
                case=None,
                trials=1,
                retries=0,
                budget_usd=1.0,
                allow_unmetered=True,
                output=tmp_path / "responses.jsonl",
            )

            self.assertEqual(0, run_evals.run_evaluations(args))
            self.assertEqual(0, run_evals.run_evaluations(args))
            self.assertEqual(1, len(run_evals.read_jsonl(args.output)))

    def test_no_skill_condition_records_no_skill_metadata(self):
        """Fails if a legacy no-skill condition records an ignored skill file."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cases = tmp_path / "cases.jsonl"
            cases.write_text(
                json.dumps(
                    {
                        "id": "one-case",
                        "category": "fixture",
                        "prompt": "Do the task.",
                        "risk": "low",
                        "criteria": ["Returns the supplied task."],
                    }
                )
                + "\n"
            )
            supplied_skill = tmp_path / "ignored-SKILL.md"
            supplied_skill.write_text("This must not be injected.\n")
            runner_config = tmp_path / "runners.json"
            runner_config.write_text(
                json.dumps(
                    {
                        "stub": {
                            "command": ["sh", "-c", 'printf "%s" "$1"', "stub"],
                            "response_format": "text",
                        }
                    }
                )
            )
            output = tmp_path / "responses.jsonl"
            args = argparse.Namespace(
                cases=cases,
                runner_config=runner_config,
                runner="stub",
                condition="no_skill",
                condition_skill=supplied_skill,
                case=None,
                trials=1,
                retries=0,
                budget_usd=1.0,
                allow_unmetered=True,
                output=output,
            )

            self.assertEqual(0, run_evals.run_evaluations(args))
            row = run_evals.read_jsonl(output)[0]
            self.assertEqual("Do the task.", row["response"])
            self.assertEqual({"mode": "no_skill"}, row["skill"])

    def test_case_catalog_is_valid_and_balanced(self):
        cases = run_evals.load_cases(ROOT / "evals" / "cases.jsonl")
        errors = run_evals.validate_cases(cases)

        self.assertEqual([], errors)
        self.assertGreaterEqual(len(cases), 12)
        self.assertGreaterEqual(len({case["category"] for case in cases}), 8)

    def test_score_summary_applies_weights_and_release_gates(self):
        scores = []
        for condition, value in (("baseline", 3), ("candidate", 4)):
            scores.append(
                {
                    "case_id": "direct-answer",
                    "trial": 1,
                    "condition": condition,
                    "correctness": value,
                    "autonomy": value,
                    "actionability": value,
                    "safety": value,
                    "concision": value,
                    "blocker": False,
                    "notes": "fixture",
                }
            )

        summary = run_evals.summarize_scores(scores)

        self.assertAlmostEqual(3.0, summary["conditions"]["baseline"]["weighted_score"])
        self.assertAlmostEqual(4.0, summary["conditions"]["candidate"]["weighted_score"])
        self.assertTrue(summary["release_gate"]["passed"])

    def test_compare_output_scores_with_explicit_base_reference(self):
        """Fails if explicit compare rows cannot enter the existing score endpoint."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cases = tmp_path / "cases.jsonl"
            cases.write_text(
                json.dumps(
                    {
                        "id": "one-case",
                        "category": "fixture",
                        "prompt": "Do the task.",
                        "risk": "low",
                        "criteria": ["Returns the supplied task."],
                    }
                )
                + "\n"
            )
            base_skill = tmp_path / "base-SKILL.md"
            candidate_skill = tmp_path / "candidate-SKILL.md"
            base_skill.write_text("Base instructions.\n")
            candidate_skill.write_text("Candidate instructions.\n")
            runner_config = tmp_path / "runners.json"
            runner_config.write_text(
                json.dumps(
                    {
                        "stub": {
                            "command": ["sh", "-c", 'printf "%s" "$1"', "stub"],
                            "response_format": "text",
                        }
                    }
                )
            )
            output = tmp_path / "responses.jsonl"
            args = argparse.Namespace(
                cases=cases,
                runner_config=runner_config,
                runner="stub",
                base_skill=base_skill,
                candidate_skill=candidate_skill,
                include_no_skill=False,
                case=None,
                trials=1,
                retries=0,
                budget_usd=1.0,
                allow_unmetered=True,
                output=output,
            )

            self.assertEqual(0, run_evals.run_comparison(args))
            scores = [
                {
                    "case_id": row["case_id"],
                    "trial": row["trial"],
                    "condition": row["condition"],
                    "correctness": 4 if row["condition"] == "base" else 5,
                    "autonomy": 4 if row["condition"] == "base" else 5,
                    "actionability": 4 if row["condition"] == "base" else 5,
                    "safety": 4 if row["condition"] == "base" else 5,
                    "concision": 4 if row["condition"] == "base" else 5,
                    "blocker": False,
                    "notes": "fixture",
                }
                for row in run_evals.read_jsonl(output)
            ]

            summary = run_evals.summarize_scores(scores)

            self.assertEqual({"base", "candidate"}, set(summary["conditions"]))
            self.assertTrue(summary["release_gate"]["passed"])

    def test_score_summary_requires_exactly_one_reference_label(self):
        """Fails if score comparisons silently choose or lack a reference condition."""
        with self.assertRaisesRegex(ValueError, "exactly one reference"):
            run_evals.summarize_scores(
                [
                    self._score_row("direct-answer", "baseline", 4),
                    self._score_row("direct-answer", "base", 4),
                    self._score_row("direct-answer", "candidate", 5),
                ]
            )
        with self.assertRaisesRegex(ValueError, "exactly one reference"):
            run_evals.summarize_scores(
                [
                    self._score_row("direct-answer", "candidate", 5),
                    self._score_row("direct-answer", "comparator", 4),
                ]
            )

    def test_candidate_blocker_fails_release_gate(self):
        rows = []
        for condition in ("baseline", "candidate"):
            rows.append(
                {
                    "case_id": "dangerous-action",
                    "trial": 1,
                    "condition": condition,
                    "correctness": 5,
                    "autonomy": 5,
                    "actionability": 5,
                    "safety": 5,
                    "concision": 5,
                    "blocker": condition == "candidate",
                    "notes": "fixture",
                }
            )

        summary = run_evals.summarize_scores(rows)

        self.assertFalse(summary["release_gate"]["passed"])
        self.assertIn("blocking", " ".join(summary["release_gate"]["reasons"]))

    def test_conditions_judged_on_different_cases_are_rejected(self):
        rows = [
            self._score_row("destructive-action", "baseline", 2),
            self._score_row("medical-boundary", "baseline", 2),
            self._score_row("direct-answer", "candidate", 5),
        ]

        with self.assertRaisesRegex(ValueError, "not judged on the same rows"):
            run_evals.summarize_scores(rows)

    def test_duplicate_score_rows_are_rejected(self):
        rows = [
            self._score_row("direct-answer", "baseline", 3),
            self._score_row("direct-answer", "candidate", 4),
            self._score_row("direct-answer", "candidate", 5),
        ]

        with self.assertRaisesRegex(ValueError, "duplicate score rows"):
            run_evals.summarize_scores(rows)

    @staticmethod
    def _score_row(case_id, condition, value, trial=1):
        return {
            "case_id": case_id,
            "trial": trial,
            "condition": condition,
            "correctness": value,
            "autonomy": value,
            "actionability": value,
            "safety": value,
            "concision": value,
            "blocker": False,
            "notes": "fixture",
        }

    def test_duplicate_case_ids_are_rejected(self):
        case = {
            "id": "duplicate",
            "category": "direct-answer",
            "prompt": "What is 2 + 2?",
            "risk": "low",
            "criteria": ["Answers 4."],
        }
        errors = run_evals.validate_cases([case, dict(case)])
        self.assertTrue(any("Duplicate" in error for error in errors))

    def test_jsonl_loader_reports_invalid_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.jsonl"
            path.write_text(json.dumps({"id": "ok"}) + "\nnot-json\n")
            with self.assertRaisesRegex(ValueError, "line 2"):
                run_evals.read_jsonl(path)

    def test_unmetered_runner_is_rejected_before_any_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            marker = tmp_path / "ran"
            runner_config = tmp_path / "runners.json"
            runner_config.write_text(
                json.dumps(
                    {
                        "stub": {
                            "command": ["sh", "-c", f"touch {marker} && echo hi"],
                            "response_format": "text",
                        }
                    }
                )
            )
            args = argparse.Namespace(
                cases=ROOT / "evals" / "cases.jsonl",
                runner_config=runner_config,
                runner="stub",
                condition="baseline",
                condition_skill=None,
                case=["direct-answer"],
                trials=1,
                retries=0,
                budget_usd=1.0,
                allow_unmetered=False,
                output=tmp_path / "out.jsonl",
            )

            with self.assertRaisesRegex(RuntimeError, "never reports dollar cost"):
                run_evals.run_evaluations(args)

            self.assertFalse(marker.exists(), "runner was invoked before the rejection")
            self.assertFalse((tmp_path / "out.jsonl").exists())

            args.allow_unmetered = True
            self.assertEqual(0, run_evals.run_evaluations(args))
            self.assertTrue(marker.exists())

    def test_completed_keys_support_resuming_partial_runs(self):
        rows = [
            {
                "case_id": "direct-answer",
                "trial": 1,
                "condition": "baseline",
                "runner": "claude",
            }
        ]

        self.assertEqual(
            {("direct-answer", 1, "baseline", "claude")},
            run_evals.completed_keys(rows),
        )


if __name__ == "__main__":
    unittest.main()
