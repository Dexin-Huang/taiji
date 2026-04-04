"""Lightweight verification for taiji's stable mechanical kernel."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .agents import DualLoopState, RUN_LIBRARIAN_AGENT_NAME, RUN_LIBRARIAN_AGENT_TOOLS, make_edit_hook, run_librarian_config
from .bootstrap import bootstrap_unit
from .config import load_unit_config
from .cycle import dual_loop_paths, ensure_run_workspace, evaluate_yang_trial, run_round, seed, status, trial_beats, validate_yin
from .frontier import frontier_from_legacy, load_frontier, save_frontier
from .ideas import record_seed_idea, record_yang_idea
from .law import has_materialized_law, load_materialized_snapshot
from .loop import baseline_record_from_state, update_kept_state_from_record
from .schema import ROOT


PROMPT_TEXT = """# Goal

Verify that the taiji runtime can materialize a world, run yang, evaluate yin,
and enforce file ownership mechanically.
"""

YIN_PASSING = """def world() -> dict:
    return {
        "target": 2,
    }


def passes(results: dict) -> bool:
    return bool(results.get("yang_contract_ok")) and results.get("answer") == 2
"""

YIN_NESTED_PASSING = """def world() -> dict:
    return {
        "target": 2,
    }


def passes(results: dict) -> bool:
    summary = results.get("summary", {})
    evidence = results.get("evidence", {})
    return (
        bool(results.get("yang_contract_ok"))
        and isinstance(summary, dict)
        and summary.get("answer") == 2
        and isinstance(evidence, dict)
        and evidence.get("retention_scores") == [1.0, 0.75, 0.5]
    )
"""

YANG_PASSING = """import json
from pathlib import Path


def run() -> dict:
    world = json.loads(Path("world.json").read_text(encoding="utf-8"))
    return {
        "answer": int(world["target"]),
    }
"""

YANG_NESTED_PASSING = """import json
from pathlib import Path


def run() -> dict:
    world = json.loads(Path("world.json").read_text(encoding="utf-8"))
    return {
        "summary": {
            "answer": int(world["target"]),
        },
        "evidence": {
            "retention_scores": [1.0, 0.75, 0.5],
            "episode_flags": [True, True, False],
        },
        "artifacts": {
            "note": "nested-json-ok",
        },
    }
"""

YANG_BAD_CONTRACT = """def run() -> dict:
    return {
        "bad": {1, 2, 3},
    }
"""

YIN_IMPORT_UNSTABLE = """import random

TOKEN = random.randint(1, 1_000_000)


def world() -> dict:
    return {
        "token": TOKEN,
    }


def passes(results: dict) -> bool:
    return results.get("token") == TOKEN
"""

YIN_OTHER_TARGET = """def world() -> dict:
    return {
        "target": 999,
    }


def passes(results: dict) -> bool:
    return bool(results.get("yang_contract_ok")) and results.get("answer") == 999
"""

YIN_WITH_SCORE = """def world() -> dict:
    return {
        "target": 2,
    }


def passes(results: dict) -> bool:
    return bool(results.get("yang_contract_ok")) and results.get("summary", {}).get("error") == 0.0


def score(results: dict) -> dict:
    summary = results.get("summary", {})
    error = float(summary.get("error", 1_000_000.0))
    size = float(summary.get("size", 1_000_000.0))
    return {
        "order": [
            {"name": "error", "value": error, "direction": "min"},
            {"name": "size", "value": size, "direction": "min"},
        ],
        "summary": {
            "error": error,
            "size": size,
        },
    }
"""

YIN_BAD_SCORE_PROBE = """def world() -> dict:
    return {
        "target": 2,
    }


def passes(results: dict) -> bool:
    return False


def score(results: dict) -> dict:
    values = results.get("summary", {}).get("values", [])
    mean_value = sum(values) / len(values)
    return {
        "order": [
            {"name": "mean_value", "value": mean_value, "direction": "min"},
        ],
        "summary": {},
    }
"""

YANG_SCORE_BASELINE = """def run() -> dict:
    return {
        "summary": {
            "answer": 2,
            "error": 5.0,
            "size": 20.0,
        }
    }
"""

YANG_SCORE_BETTER = """def run() -> dict:
    return {
        "summary": {
            "answer": 2,
            "error": 3.0,
            "size": 18.0,
        }
    }
"""

YANG_SCORE_WORSE = """def run() -> dict:
    return {
        "summary": {
            "answer": 2,
            "error": 7.0,
            "size": 10.0,
        }
    }
"""

MECHANISM_YIN = """def world() -> dict:
    return {
        "tau_max": 0.2,
    }


def passes(results: dict) -> bool:
    candidate = results.get("candidate", {})
    witness = results.get("witness", {})
    return (
        bool(results.get("yang_contract_ok"))
        and isinstance(candidate, dict)
        and isinstance(witness, dict)
        and candidate.get("mechanism") == "ema_anchor"
        and float(witness.get("tau", 1.0)) <= 0.2
        and "bounded-drift" in results.get("derivation", "")
    )
"""

MECHANISM_IMPLEMENTATION = """def compile_candidate(candidate: dict, witness: dict) -> dict:
    return {
        "candidate": candidate,
        "witness": witness,
    }
"""

MECHANISM_CANDIDATE = {
    "mechanism": "ema_anchor",
    "family": "retained_linear_fast_weights",
}

MECHANISM_WITNESS = {
    "tau": 0.125,
    "delta": 0.01,
}

MECHANISM_DERIVATION = """# Derivation

Use bounded-drift EMA to keep the encoder inside the target cosine band.
"""


class SmokeFailure(RuntimeError):
    """Raised when a smoke check fails."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def _workspace_temp_dir(prefix: str) -> Path:
    base = ROOT / ".tmp-taiji-smoke"
    base.mkdir(parents=True, exist_ok=True)
    directory = base / f"{prefix}{uuid.uuid4().hex}"
    directory.mkdir(parents=True, exist_ok=False)
    return directory


@contextmanager
def temporary_unit() -> Iterator[tuple[Path, Any]]:
    unit_root = _workspace_temp_dir("smoke-")
    try:
        bootstrap_unit(unit_root, prompt_text=PROMPT_TEXT, include_readme=False)
        paths = dual_loop_paths(unit_root)
        try:
            yield unit_root, paths
        finally:
            shutil.rmtree(paths.run_root.parent, ignore_errors=True)
    finally:
        shutil.rmtree(unit_root, ignore_errors=True)


def _write_unit(paths: Any, *, yin_text: str, yang_text: str) -> None:
    paths.yin_seed_path.write_text(yin_text, encoding="utf-8")
    paths.yang_seed_path.write_text(yang_text, encoding="utf-8")
    paths.yin_path.unlink(missing_ok=True)
    paths.yang_path.unlink(missing_ok=True)


def _assert_compact_idea_shape(record: dict[str, Any], *, label: str) -> None:
    _require(isinstance(record, dict), f"{label} frontier idea must be a dict")
    _require(isinstance(record.get("id"), str) and bool(record.get("id")), f"{label} frontier idea missing id")
    _require(record.get("agent") in {"yin", "yang"}, f"{label} frontier idea missing agent")
    _require(isinstance(record.get("iteration"), int), f"{label} frontier idea missing iteration")
    _require(isinstance(record.get("status"), str) and bool(record.get("status")), f"{label} frontier idea missing status")
    _require(isinstance(record.get("summary"), str), f"{label} frontier idea missing summary")
    _require(isinstance(record.get("tags"), list), f"{label} frontier idea missing tags")
    _require(isinstance(record.get("artifact_dir"), str), f"{label} frontier idea missing artifact_dir")
    _require(isinstance(record.get("parent_ids"), list), f"{label} frontier idea missing parent_ids")


def _assert_frontier_idea_summary_shape(payload: dict[str, Any], *, label: str) -> None:
    _require(isinstance(payload, dict), f"{label} frontier idea_summary must be a dict")
    _require(isinstance(payload.get("latest"), dict), f"{label} frontier idea_summary missing latest")
    _require(isinstance(payload.get("recent"), list), f"{label} frontier idea_summary missing recent")
    _require(isinstance(payload.get("open_failed_ideas"), list), f"{label} frontier idea_summary missing open_failed_ideas")
    _require(isinstance(payload.get("tag_counts"), dict), f"{label} frontier idea_summary missing tag_counts")
    _assert_compact_idea_shape(payload["latest"], label=f"{label}.latest")
    latest_yang = payload.get("latest_yang")
    if latest_yang is not None:
        _assert_compact_idea_shape(latest_yang, label=f"{label}.latest_yang")
    latest_yin = payload.get("latest_yin")
    if latest_yin is not None:
        _assert_compact_idea_shape(latest_yin, label=f"{label}.latest_yin")
    for index, record in enumerate(payload["recent"]):
        _assert_compact_idea_shape(record, label=f"{label}.recent[{index}]")
    for index, record in enumerate(payload["open_failed_ideas"]):
        _assert_compact_idea_shape(record, label=f"{label}.open_failed_ideas[{index}]")


def _assert_incumbent_cache_shape() -> None:
    state = DualLoopState()
    record = {
        "passed": True,
        "score": {
            "order": [
                {"name": "slack", "value": 1.0, "direction": "max"},
            ],
            "summary": {
                "slack": 1.0,
            },
        },
    }
    update_kept_state_from_record(state, record, source_hash="abc123")
    cached = baseline_record_from_state(state, source_hash="abc123")
    _require(
        cached == {
            "candidate_id": None,
            "passed": True,
            "score": record["score"],
            "source_hash": "abc123",
        },
        "incumbent cache shape did not round-trip",
    )
    _require(baseline_record_from_state(state, source_hash="other") is None, "incumbent cache should be source-hash scoped")
    update_kept_state_from_record(state, record, source_hash="abc123", candidate_id="cand-1")
    cached_with_candidate = baseline_record_from_state(state, source_hash="abc123")
    _require(
        cached_with_candidate == {
            "candidate_id": "cand-1",
            "passed": True,
            "score": record["score"],
            "source_hash": "abc123",
        },
        "incumbent cache should preserve candidate ids when present",
    )


def _assert_frontier_state_shape(frontier: Any, *, label: str) -> None:
    _require(getattr(frontier, "schema_version", None) == 1, f"{label} frontier schema version should be 1")
    _require(isinstance(getattr(frontier, "candidates", None), tuple), f"{label} frontier candidates must be a tuple")
    _require(isinstance(getattr(frontier, "members", None), tuple), f"{label} frontier members must be a tuple")
    _require(getattr(frontier, "selection_policy", None) == "incumbent_only", f"{label} frontier should default to incumbent_only")
    _require(getattr(frontier, "max_live_members", None) == 1, f"{label} frontier should default to one live member")
    _require(isinstance(getattr(frontier, "idea_summary", None), dict), f"{label} frontier idea_summary must be a dict")


def run_kernel_check() -> dict[str, Any]:
    with temporary_unit() as (_, paths):
        _write_unit(paths, yin_text=YIN_PASSING, yang_text=YANG_PASSING)

        seed_record = seed(paths)
        round_record = run_round(paths, auto_seed=False)
        status_record = status(paths)
        results = json.loads(paths.results_path.read_text(encoding="utf-8"))

        _require(seed_record["phase"] == "seed", "seed did not record a seed phase")
        _require(round_record["phase"] == "round", "round did not record a round phase")
        _require(bool(round_record["passed"]), "passing smoke unit did not pass")
        _require(results.get("answer") == 2, "yang result did not propagate through run_round")
        _require(status_record.get("latest", {}).get("passed") is True, "status did not report latest pass")
        _require(paths.law_path.exists(), "law.md was not materialized")
        _require(paths.world_path.exists(), "world.json was not materialized")
        _require(paths.history_path.exists(), "history.ndjson was not materialized")
        _require(paths.yin_snapshot_path.exists(), "yin.snapshot.py was not materialized")
        _require(paths.law_state_path.exists(), "law_state.json was not materialized")

        return {
            "name": "kernel",
            "ok": True,
            "seed_phase": seed_record["phase"],
            "round_phase": round_record["phase"],
            "passed": round_record["passed"],
            "result_keys": sorted(results.keys()),
        }


def run_contract_failure_check() -> dict[str, Any]:
    with temporary_unit() as (_, paths):
        _write_unit(paths, yin_text=YIN_PASSING, yang_text=YANG_BAD_CONTRACT)

        round_record = run_round(paths)
        results = json.loads(paths.results_path.read_text(encoding="utf-8"))

        _require(round_record["passed"] is False, "contract violation should not pass")
        _require(results.get("yang_contract_ok") is False, "bad yang result was not normalized as a contract failure")
        _require("unsupported type set" in str(results.get("error", "")), "contract failure did not preserve a readable error")

        return {
            "name": "contract_failure",
            "ok": True,
            "passed": round_record["passed"],
            "error": results.get("error"),
        }


def run_nested_submission_check() -> dict[str, Any]:
    with temporary_unit() as (_, paths):
        _write_unit(paths, yin_text=YIN_NESTED_PASSING, yang_text=YANG_NESTED_PASSING)

        round_record = run_round(paths)
        results = json.loads(paths.results_path.read_text(encoding="utf-8"))

        _require(round_record["passed"] is True, "nested JSON submission should pass")
        _require(results.get("summary", {}).get("answer") == 2, "nested summary was not preserved")
        _require(results.get("evidence", {}).get("retention_scores") == [1.0, 0.75, 0.5], "nested list evidence was not preserved")

        return {
            "name": "nested_submission",
            "ok": True,
            "passed": round_record["passed"],
            "result_keys": sorted(results.keys()),
        }


def run_import_stability_check() -> dict[str, Any]:
    with temporary_unit() as (_, paths):
        _write_unit(paths, yin_text=YIN_IMPORT_UNSTABLE, yang_text=YANG_PASSING)
        try:
            validate_yin(paths, {"token": 1})
        except RuntimeError as exc:
            message = str(exc)
            _require("stable across fresh imports" in message, "unstable yin did not surface the right failure")
            return {
                "name": "import_stability",
                "ok": True,
                "error": message,
            }
        raise SmokeFailure("unstable yin unexpectedly validated")


def run_fixed_snapshot_check() -> dict[str, Any]:
    with temporary_unit() as (_, paths):
        _write_unit(paths, yin_text=YIN_PASSING, yang_text=YANG_PASSING)
        seed(paths)
        _require(has_materialized_law(paths), "seed did not materialize an active law snapshot")
        original_world = json.loads(paths.world_path.read_text(encoding="utf-8"))

        paths.yin_path.write_text(YIN_OTHER_TARGET, encoding="utf-8")
        round_record = run_round(paths, auto_seed=False)
        world_after = json.loads(paths.world_path.read_text(encoding="utf-8"))
        results = json.loads(paths.results_path.read_text(encoding="utf-8"))

        _require(round_record["passed"] is True, "round should still pass against the materialized law snapshot")
        _require(results.get("answer") == 2, "yang should still read the frozen world snapshot")
        _require(world_after == original_world, "world.json should remain frozen until yin is re-seeded")

        return {
            "name": "fixed_snapshot",
            "ok": True,
            "world": world_after,
            "passed": round_record["passed"],
        }


def run_adaptive_probe_check() -> dict[str, Any]:
    with temporary_unit() as (_, paths):
        _write_unit(paths, yin_text=YIN_PASSING, yang_text=YANG_PASSING)
        seed(paths)
        round_record = run_round(paths, auto_seed=False)
        _require(round_record["passed"] is True, "baseline round did not pass before adaptive tightening")
        paths.yin_path.write_text(YIN_OTHER_TARGET, encoding="utf-8")
        validation = validate_yin(paths, round_record["results"])
        _require(validation.probe_passed is False, "old results should fail under the tightened law")
        return {
            "name": "adaptive_probe",
            "ok": True,
            "probe_passed": validation.probe_passed,
            "new_world": validation.snapshot.world,
        }


def run_seed_workspace_check() -> dict[str, Any]:
    with temporary_unit() as (_, paths):
        _write_unit(paths, yin_text=YIN_PASSING, yang_text=YANG_PASSING)
        seed(paths)

        _require(paths.yin_path.exists(), "run-local yin working copy was not materialized")
        _require(paths.yang_path.exists(), "run-local yang working copy was not materialized")
        _require(
            paths.yin_seed_path.read_text(encoding="utf-8") == YIN_PASSING,
            "unit yin seed changed during seed materialization",
        )
        _require(
            paths.yang_seed_path.read_text(encoding="utf-8") == YANG_PASSING,
            "unit yang seed changed during seed materialization",
        )

        paths.yin_path.write_text(YIN_OTHER_TARGET, encoding="utf-8")
        _require(
            paths.yin_seed_path.read_text(encoding="utf-8") == YIN_PASSING,
            "editing the run-local yin file should not mutate the unit seed",
        )

        return {
            "name": "seed_workspace",
            "ok": True,
            "yin_seed": paths.yin_seed_path.name,
            "yin_work": paths.yin_path.name,
        }


def run_run_id_selection_check() -> dict[str, Any]:
    with temporary_unit() as (unit_root, _):
        first = dual_loop_paths(unit_root, create_run=True)
        ensure_run_workspace(first)
        resumed = dual_loop_paths(unit_root, create_run=True)
        _require(resumed.run_id == first.run_id, "existing run should be resumed when no --new is requested")

        fresh = dual_loop_paths(unit_root, create_run=True, new_run=True)
        ensure_run_workspace(fresh)
        _require(fresh.run_id != first.run_id, "--new should allocate a fresh run id")
        _require(json.loads(fresh.current_run_path.read_text(encoding="utf-8")).get("run_id") == fresh.run_id, "current run pointer did not update")
        _require(first.run_root.exists(), "first run root was not materialized")
        _require(fresh.run_root.exists(), "fresh run root was not materialized")

        return {
            "name": "run_id_selection",
            "ok": True,
            "resumed_run_id": resumed.run_id,
            "fresh_run_id": fresh.run_id,
        }


def run_librarian_config_check() -> dict[str, Any]:
    with temporary_unit() as (_, paths):
        config = run_librarian_config(paths, ROOT)
        prompt = str(config["prompt"])
        _require(config["name"] == RUN_LIBRARIAN_AGENT_NAME, "librarian agent name changed unexpectedly")
        _require(config["tools"] == RUN_LIBRARIAN_AGENT_TOOLS, "librarian tools should stay read-only")
        _require("Treat every invocation as stateless." in prompt, "librarian prompt lost the statelessness rule")
        _require(relative_artifact_fragment(paths.run_root) in prompt, "librarian prompt should mention the active run root")
        _require(relative_artifact_fragment(paths.ideas_path) in prompt, "librarian prompt should mention ideas.ndjson")
        _require(relative_artifact_fragment(paths.frontier_path) in prompt, "librarian prompt should mention frontier.json")
        return {
            "name": "librarian_config",
            "ok": True,
            "agent_name": config["name"],
            "tools": config["tools"],
        }


def run_score_comparator_check() -> dict[str, Any]:
    with temporary_unit() as (_, paths):
        _write_unit(paths, yin_text=YIN_WITH_SCORE, yang_text=YANG_SCORE_BASELINE)
        seed(paths)
        snapshot = load_materialized_snapshot(paths)

        baseline = evaluate_yang_trial(paths, snapshot, persist_results=False, persist_history=False, phase="baseline")
        _require(baseline["score"]["summary"]["error"] == 5.0, "baseline score was not recorded")

        paths.yang_path.write_text(YANG_SCORE_BETTER, encoding="utf-8")
        better = evaluate_yang_trial(paths, snapshot, persist_results=False, persist_history=False, phase="trial")
        _require(trial_beats(better, baseline), "better ordered score should beat the baseline")

        paths.yang_path.write_text(YANG_SCORE_WORSE, encoding="utf-8")
        worse = evaluate_yang_trial(paths, snapshot, persist_results=False, persist_history=False, phase="trial")
        _require(not trial_beats(worse, baseline), "worse ordered score should not beat the baseline")

        return {
            "name": "score_comparator",
            "ok": True,
            "baseline_score": baseline["score"],
            "better_score": better["score"],
            "worse_score": worse["score"],
        }


def run_score_probe_failure_check() -> dict[str, Any]:
    with temporary_unit() as (_, paths):
        _write_unit(paths, yin_text=YIN_BAD_SCORE_PROBE, yang_text=YANG_PASSING)
        try:
            validate_yin(paths)
        except RuntimeError as exc:
            message = str(exc)
            _require(
                "empty, partial, or failed results" in message,
                "score probe failure did not surface the new guidance",
            )
            return {
                "name": "score_probe_failure",
                "ok": True,
                "error": message,
            }
        raise SmokeFailure("unsafe yin.score unexpectedly validated")


def run_unit_config_check() -> dict[str, Any]:
    with temporary_unit() as (unit_root, _):
        (unit_root / "spec.md").write_text(PROMPT_TEXT, encoding="utf-8")
        (unit_root / "builder.py").write_text(YANG_PASSING, encoding="utf-8")
        (unit_root / "critic.py").write_text(YIN_PASSING, encoding="utf-8")
        (unit_root / "unit.toml").write_text(
            """name = "demo"
kind = "yin_yang"
prompt_set = "yin_yang"

[entry]
prompt = "spec.md"
yang = "builder.py"
yin = "critic.py"
""",
            encoding="utf-8",
        )
        resolved = dual_loop_paths(unit_root)
        _require(resolved.prompt_path.name == "spec.md", "unit.toml did not control the prompt entry")
        _require(resolved.yang_path.name == "builder.py", "unit.toml did not control the yang entry")
        _require(resolved.yin_path.name == "critic.py", "unit.toml did not control the yin entry")
        _require(resolved.yang_prompt_path.exists(), "shared prompt resolution did not find the configured prompt set")
        return {
            "name": "unit_config",
            "ok": True,
            "prompt": resolved.prompt_path.name,
            "yang": resolved.yang_path.name,
            "yin": resolved.yin_path.name,
        }


def run_frontier_defaults_check() -> dict[str, Any]:
    with temporary_unit() as (unit_root, paths):
        config = load_unit_config(unit_root)
        _require(config.kind == "yin_yang", "default unit kind should remain canonical")
        _require(config.problem_kind == "program_search", "default problem kind should remain program_search")
        _require(config.prompt_set == "yin_yang", "default prompt set should remain yin_yang")
        _require(config.yang_entry == "yang.py", "default scaffold should keep yang.py")
        _require(config.yin_entry == "yin.py", "default scaffold should keep yin.py")
        _assert_incumbent_cache_shape()

        state = DualLoopState()
        update_kept_state_from_record(
            state,
            {
                "passed": True,
                "score": {"order": [], "summary": {"slack": 1.0}},
            },
            source_hash="legacy-source",
            candidate_id="legacy-incumbent",
        )
        legacy_frontier = frontier_from_legacy(paths, state=state)
        _assert_frontier_state_shape(legacy_frontier, label="legacy")
        _require(legacy_frontier.incumbent_candidate_id == "legacy-incumbent", "legacy frontier should preserve incumbent candidate id")
        _require(len(legacy_frontier.candidates) == 1, "legacy frontier should synthesize one incumbent candidate")
        _require(len(legacy_frontier.members) == 1, "legacy frontier should synthesize one incumbent member")
        save_frontier(paths, legacy_frontier)
        roundtrip_frontier = load_frontier(paths)
        _require(roundtrip_frontier is not None, "saved frontier should load back")
        _assert_frontier_state_shape(roundtrip_frontier, label="roundtrip")
        _require(roundtrip_frontier.incumbent_candidate_id == "legacy-incumbent", "round-tripped frontier lost incumbent id")

        _write_unit(paths, yin_text=YIN_PASSING, yang_text=YANG_PASSING)
        seed(paths)
        seed_snapshot = load_materialized_snapshot(paths)
        record_seed_idea(
            paths,
            ROOT,
            artifact_dir=paths.run_root,
            response=paths.yin_path.read_text(encoding="utf-8"),
            changed=False,
            world=seed_snapshot.world,
        )
        frontier_after_seed = load_frontier(paths)
        _require(frontier_after_seed is not None, "frontier should still load after seed summary update")
        _assert_frontier_state_shape(frontier_after_seed, label="seed")
        _assert_frontier_idea_summary_shape(frontier_after_seed.idea_summary, label="seed.idea_summary")
        _require(frontier_after_seed.idea_summary["latest"]["agent"] == "yin", "seed frontier should be seeded by yin")
        _require(frontier_after_seed.idea_summary["latest_yang"] is None, "seed frontier should not yet have a yang idea")
        _require(frontier_after_seed.idea_summary["latest_yin"]["agent"] == "yin", "seed frontier should record latest yin idea")
        _require(frontier_after_seed.incumbent_candidate_id == "legacy-incumbent", "seed frontier should preserve incumbent candidate id")

        round_record = run_round(paths, auto_seed=False)
        _require(bool(round_record["passed"]), "default incumbent behavior should still pass the baseline round")
        record_yang_idea(
            paths,
            ROOT,
            iteration=1,
            artifact_dir=paths.run_root,
            response="default incumbent round",
            after_text=paths.yang_path.read_text(encoding="utf-8"),
            record=round_record,
            selection={"action": "keep", "reason": "default incumbent"},
        )
        frontier_after_round = load_frontier(paths)
        _require(frontier_after_round is not None, "frontier should still load after round summary update")
        _assert_frontier_state_shape(frontier_after_round, label="round")
        _assert_frontier_idea_summary_shape(frontier_after_round.idea_summary, label="round.idea_summary")
        _require(frontier_after_round.idea_summary["latest"]["agent"] == "yang", "round frontier should record the current yang idea")
        _require(frontier_after_round.idea_summary["latest"]["status"] == "passed", "round frontier should record a passing yang idea")
        _require(frontier_after_round.idea_summary["latest_yang"]["agent"] == "yang", "round frontier should track the latest yang idea")
        _require(frontier_after_round.idea_summary["latest_yin"]["agent"] == "yin", "round frontier should still track the latest yin idea")
        _require(frontier_after_round.incumbent_candidate_id == "legacy-incumbent", "round frontier should preserve incumbent id without loop integration")

        return {
            "name": "frontier_defaults",
            "ok": True,
            "kind": config.kind,
            "problem_kind": config.problem_kind,
            "frontier_keys": sorted(frontier_after_round.to_json().keys()),
        }


def run_mechanism_search_check() -> dict[str, Any]:
    unit_root = _workspace_temp_dir("mech-")
    try:
        bootstrap_unit(
            unit_root,
            prompt_text=PROMPT_TEXT,
            problem_kind="mechanism_search",
            include_readme=False,
        )
        (unit_root / "yin.py").write_text(MECHANISM_YIN, encoding="utf-8")
        (unit_root / "implementation.py").write_text(MECHANISM_IMPLEMENTATION, encoding="utf-8")
        (unit_root / "candidate.json").write_text(json.dumps(MECHANISM_CANDIDATE, indent=2) + "\n", encoding="utf-8")
        (unit_root / "witness.json").write_text(json.dumps(MECHANISM_WITNESS, indent=2) + "\n", encoding="utf-8")
        (unit_root / "derivation.md").write_text(MECHANISM_DERIVATION, encoding="utf-8")

        paths = dual_loop_paths(unit_root)
        _require(paths.config.kind == "yin_yang", "mechanism_search should keep the loop kind canonical")
        _require(paths.config.problem_kind == "mechanism_search", "mechanism_search config was not loaded")
        _require(paths.yang_path.name == "implementation.py", "mechanism_search did not use implementation.py")
        ensure_run_workspace(paths)
        _require(paths.yang_candidate_path.exists(), "candidate.json was not copied into the run workspace")
        _require(paths.yin_problem_spec_path.exists(), "problem_spec.md was not copied into the run workspace")

        seed(paths)
        snapshot = load_materialized_snapshot(paths)
        record = evaluate_yang_trial(paths, snapshot, persist_results=False, persist_history=False, phase="trial")
        _require(record["passed"], "mechanism_search candidate did not pass")
        _require(record["results"]["candidate"]["mechanism"] == "ema_anchor", "candidate artifact was not loaded into results")
        _require(record["results"]["witness"]["tau"] == 0.125, "witness artifact was not loaded into results")

        return {
            "name": "mechanism_search",
            "ok": True,
            "run_prompt": paths.yang_prompt_path.name,
            "candidate_path": paths.yang_candidate_path.name,
            "problem_spec_path": paths.yin_problem_spec_path.name,
        }
    finally:
        shutil.rmtree(unit_root, ignore_errors=True)


def run_scaffold_reinit_check() -> dict[str, Any]:
    unit_root = _workspace_temp_dir("reinit-")
    try:
        initial = bootstrap_unit(unit_root, prompt_text=PROMPT_TEXT, include_readme=False)
        initial_toml = (unit_root / "unit.toml").read_text(encoding="utf-8")
        _require((unit_root / "yang.py").exists(), "default scaffold did not create yang.py")
        _require('implementation = "implementation.py"' not in initial_toml, "program_search scaffold wrote redundant implementation entry")
        _require('yang_candidate_entry = "candidate.json"' not in initial_toml, "program_search scaffold wrote redundant mechanism aliases")

        migrated = bootstrap_unit(
            unit_root,
            prompt_text=PROMPT_TEXT,
            problem_kind="mechanism_search",
            force=True,
            include_readme=False,
        )
        migrated_toml = (unit_root / "unit.toml").read_text(encoding="utf-8")
        migrated_config = load_unit_config(unit_root)
        _require(migrated_config.kind == "yin_yang", "reinitialized config did not keep canonical loop kind")
        _require(migrated_config.problem_kind == "mechanism_search", "reinitialized config did not switch problem kind")
        _require((unit_root / "implementation.py").exists(), "mechanism_search scaffold did not create implementation.py")
        _require((unit_root / "candidate.json").exists(), "mechanism_search scaffold did not create candidate.json")
        _require(not (unit_root / "yang.py").exists(), "obsolete yang.py was not removed during migration")
        _require('implementation = "implementation.py"' not in migrated_toml, "mechanism_search scaffold wrote redundant implementation alias")
        _require('yang_candidate_entry = "candidate.json"' not in migrated_toml, "mechanism_search scaffold wrote redundant mechanism aliases")

        reverted = bootstrap_unit(
            unit_root,
            prompt_text=PROMPT_TEXT,
            problem_kind="program_search",
            force=True,
            include_readme=False,
        )
        reverted_toml = (unit_root / "unit.toml").read_text(encoding="utf-8")
        reverted_config = load_unit_config(unit_root)
        _require(reverted_config.problem_kind == "program_search", "problem kind did not revert to program_search")
        _require((unit_root / "yang.py").exists(), "program_search scaffold did not restore yang.py")
        _require(not (unit_root / "implementation.py").exists(), "obsolete implementation.py was not removed on revert")
        _require(not (unit_root / "candidate.json").exists(), "obsolete candidate.json was not removed on revert")
        _require('candidate = "candidate.json"' not in reverted_toml, "reverted program_search scaffold kept mechanism entries")

        return {
            "name": "scaffold_reinit",
            "ok": True,
            "initial_problem_kind": initial["problem_kind"],
            "migrated_problem_kind": migrated["problem_kind"],
            "reverted_problem_kind": reverted["problem_kind"],
        }
    finally:
        shutil.rmtree(unit_root, ignore_errors=True)


def run_ownership_check() -> dict[str, Any]:
    root = _workspace_temp_dir("hook-")
    try:
        owned = (root / "owned.py").resolve()
        other = (root / "other.py").resolve()
        hook = make_edit_hook({owned}, root, root)

        allowed = asyncio.run(hook({
            "tool_name": "Write",
            "tool_input": {"file_path": "owned.py"},
        }, None, {}))
        denied = asyncio.run(hook({
            "tool_name": "Edit",
            "tool_input": {"file_path": "other.py"},
        }, None, {}))

        allow_decision = allowed.get("hookSpecificOutput", {}).get("permissionDecision")
        deny_decision = denied.get("hookSpecificOutput", {}).get("permissionDecision")
        deny_reason = denied.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")

        _require(allow_decision == "allow", "owned file edit was not allowed")
        _require(deny_decision == "deny", "foreign file edit was not denied")
        _require("owned.py" in deny_reason, "deny reason did not name the editable file set")

        return {
            "name": "ownership",
            "ok": True,
            "allow_decision": allow_decision,
            "deny_decision": deny_decision,
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)


def relative_artifact_fragment(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def run_selected_checks(selection: str) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    if selection in {"all", "kernel"}:
        checks.append(run_kernel_check())
    if selection in {"all", "contract_failure"}:
        checks.append(run_contract_failure_check())
    if selection in {"all", "nested_submission"}:
        checks.append(run_nested_submission_check())
    if selection in {"all", "import_stability"}:
        checks.append(run_import_stability_check())
    if selection in {"all", "fixed_snapshot"}:
        checks.append(run_fixed_snapshot_check())
    if selection in {"all", "adaptive_probe"}:
        checks.append(run_adaptive_probe_check())
    if selection in {"all", "seed_workspace"}:
        checks.append(run_seed_workspace_check())
    if selection in {"all", "run_id_selection"}:
        checks.append(run_run_id_selection_check())
    if selection in {"all", "librarian_config"}:
        checks.append(run_librarian_config_check())
    if selection in {"all", "score_comparator"}:
        checks.append(run_score_comparator_check())
    if selection in {"all", "score_probe_failure"}:
        checks.append(run_score_probe_failure_check())
    if selection in {"all", "unit_config"}:
        checks.append(run_unit_config_check())
    if selection in {"all", "frontier_defaults"}:
        checks.append(run_frontier_defaults_check())
    if selection in {"all", "mechanism_search"}:
        checks.append(run_mechanism_search_check())
    if selection in {"all", "scaffold_reinit"}:
        checks.append(run_scaffold_reinit_check())
    if selection in {"all", "ownership"}:
        checks.append(run_ownership_check())
    return checks


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run lightweight taiji smoke checks")
    parser.add_argument(
        "--check",
        choices=("all", "kernel", "contract_failure", "nested_submission", "import_stability", "fixed_snapshot", "adaptive_probe", "seed_workspace", "run_id_selection", "librarian_config", "score_comparator", "score_probe_failure", "unit_config", "frontier_defaults", "mechanism_search", "scaffold_reinit", "ownership"),
        default="all",
        help="Select which lightweight check to run",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    checks = run_selected_checks(args.check)
    print(json.dumps({
        "ok": True,
        "check_count": len(checks),
        "checks": checks,
    }, indent=2, sort_keys=False))


if __name__ == "__main__":
    main()
