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

from .agents import make_edit_hook
from .bootstrap import bootstrap_unit
from .cycle import dual_loop_paths, run_round, seed, status, validate_yin
from .law import has_materialized_law
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

YANG_PASSING = """import json
from pathlib import Path


def run() -> dict:
    world = json.loads(Path("world.json").read_text(encoding="utf-8"))
    return {
        "answer": int(world["target"]),
    }
"""

YANG_BAD_CONTRACT = """def run() -> dict:
    return {
        "nested": {
            "bad": True,
        },
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


class SmokeFailure(RuntimeError):
    """Raised when a smoke check fails."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def _workspace_temp_dir(prefix: str) -> Path:
    base = ROOT / "tmp_taiji"
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
    paths.yin_path.write_text(yin_text, encoding="utf-8")
    paths.yang_path.write_text(yang_text, encoding="utf-8")


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
        _require("contract violation" in str(results.get("error", "")), "contract failure did not preserve a readable error")

        return {
            "name": "contract_failure",
            "ok": True,
            "passed": round_record["passed"],
            "error": results.get("error"),
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


def run_selected_checks(selection: str) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    if selection in {"all", "kernel"}:
        checks.append(run_kernel_check())
    if selection in {"all", "contract_failure"}:
        checks.append(run_contract_failure_check())
    if selection in {"all", "import_stability"}:
        checks.append(run_import_stability_check())
    if selection in {"all", "fixed_snapshot"}:
        checks.append(run_fixed_snapshot_check())
    if selection in {"all", "adaptive_probe"}:
        checks.append(run_adaptive_probe_check())
    if selection in {"all", "unit_config"}:
        checks.append(run_unit_config_check())
    if selection in {"all", "ownership"}:
        checks.append(run_ownership_check())
    return checks


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run lightweight taiji smoke checks")
    parser.add_argument(
        "--check",
        choices=("all", "kernel", "contract_failure", "import_stability", "fixed_snapshot", "adaptive_probe", "unit_config", "ownership"),
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
