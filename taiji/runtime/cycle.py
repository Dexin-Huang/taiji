"""Shared taiji yin/yang cycle.

Each unit owns only its goal and the law/solution pair described by `unit.toml`.
The host stays mechanical: it materializes a law snapshot, runs yang inside that
snapshot, and records the resulting artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
import sys
import time
import types
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .bootstrap import bootstrap_unit, resolve_new_unit_root
from .config import (
    DEFAULT_PROBLEM_KIND,
    MECHANISM_SEARCH_KIND,
    UNIT_CONFIG_NAME,
    UnitConfig,
    load_unit_config,
    resolve_prompt_path,
)
from .law import (
    LawSnapshot,
    YinValidation,
    build_law_snapshot,
    compare_scorecards,
    evaluate_snapshot,
    has_materialized_law,
    load_materialized_snapshot,
    materialize_law_snapshot,
    score_snapshot,
    scorecard_from_json,
    validate_live_yin,
    write_law,
)
from .schema import ROOT, append_ndjson, iso_timestamp_now, resolve_unit_root, write_json

JSONScalar = str | int | float | bool | None
JSONValue = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]
JSONObject = dict[str, JSONValue]


@dataclass(frozen=True)
class DualLoopPaths:
    unit_root: Path
    unit_config_path: Path
    runs_root: Path
    current_run_path: Path
    run_id: str
    run_root: Path
    queue_root: Path
    prompt_path: Path
    yang_seed_path: Path
    yin_seed_path: Path
    yang_candidate_seed_path: Path
    yang_witness_seed_path: Path
    yang_derivation_seed_path: Path
    yin_problem_spec_seed_path: Path
    yin_counterexamples_seed_path: Path
    yang_path: Path
    yin_path: Path
    yang_candidate_path: Path
    yang_witness_path: Path
    yang_derivation_path: Path
    yin_problem_spec_path: Path
    yin_counterexamples_path: Path
    yang_scratchpad_path: Path
    yin_scratchpad_path: Path
    yang_notebook_path: Path
    yin_notebook_path: Path
    workspace_path: Path
    yang_prompt_path: Path
    yin_prompt_path: Path
    yin_seed_prompt_path: Path
    yang_system_prompt_path: Path
    yin_system_prompt_path: Path
    world_path: Path
    law_path: Path
    law_state_path: Path
    yin_snapshot_path: Path
    results_path: Path
    history_path: Path
    ideas_path: Path
    frontier_path: Path
    config: UnitConfig


def run_slug_for_unit(root: Path) -> Path:
    units_root = ROOT / "units"
    if root == ROOT:
        return Path("root")
    if root.is_relative_to(units_root):
        return root.relative_to(units_root)
    if root.is_relative_to(ROOT):
        return root.relative_to(ROOT)
    digest = hashlib.sha1(str(root).encode("utf-8")).hexdigest()[:10]
    return Path("external") / f"{root.name}-{digest}"


def runs_root_for_unit(root: Path) -> Path:
    return ROOT / "runs" / run_slug_for_unit(root)


def current_run_path_for_unit(root: Path) -> Path:
    return runs_root_for_unit(root) / "current.json"


def list_run_ids(root: Path) -> list[str]:
    runs_root = runs_root_for_unit(root)
    if not runs_root.exists():
        return []
    run_ids = sorted(entry.name for entry in runs_root.iterdir() if entry.is_dir())
    return run_ids


def read_current_run_id(root: Path) -> str | None:
    current_path = current_run_path_for_unit(root)
    if current_path.exists():
        payload = json.loads(current_path.read_text(encoding="utf-8"))
        run_id = payload.get("run_id")
        if isinstance(run_id, str) and run_id.strip():
            return run_id.strip()
    existing = list_run_ids(root)
    if "current" in existing:
        return "current"
    if existing:
        return existing[-1]
    return None


def write_current_run_id(root: Path, run_id: str) -> None:
    write_json(current_run_path_for_unit(root), {
        "run_id": run_id,
        "updated_at": iso_timestamp_now(),
    })


def allocate_run_id(root: Path) -> str:
    runs_root = runs_root_for_unit(root)
    runs_root.mkdir(parents=True, exist_ok=True)
    base = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    candidate = base
    suffix = 2
    while (runs_root / candidate).exists():
        candidate = f"{base}-{suffix:02d}"
        suffix += 1
    return candidate


def resolve_run_id(
    root: Path,
    run_id: str | None = None,
    *,
    create_run: bool = False,
    new_run: bool = False,
) -> str:
    if run_id and new_run:
        raise RuntimeError("Use either --run-id or --new, not both.")
    if new_run:
        selected = allocate_run_id(root)
        write_current_run_id(root, selected)
        return selected
    if run_id:
        if create_run:
            write_current_run_id(root, run_id)
        return run_id
    current = read_current_run_id(root)
    if current is not None:
        return current
    if create_run:
        selected = allocate_run_id(root)
        write_current_run_id(root, selected)
        return selected
    return allocate_run_id(root)


def resolve_run_root(root: Path, run_id: str) -> Path:
    return runs_root_for_unit(root) / run_id


def dual_loop_paths(
    unit_root: Path | str,
    *,
    run_id: str | None = None,
    create_run: bool = False,
    new_run: bool = False,
) -> DualLoopPaths:
    root = resolve_unit_root(unit_root)
    config = load_unit_config(root)
    selected_run_id = resolve_run_id(root, run_id, create_run=create_run, new_run=new_run)
    run_root = resolve_run_root(root, selected_run_id)
    prompt_set = config.prompt_set
    yang_candidate_entry = getattr(config, "yang_candidate_entry", "candidate.json")
    yang_witness_entry = getattr(config, "yang_witness_entry", "witness.json")
    yang_derivation_entry = getattr(config, "yang_derivation_entry", "derivation.md")
    yin_problem_spec_entry = getattr(config, "yin_problem_spec_entry", "problem_spec.md")
    yin_counterexamples_entry = getattr(config, "yin_counterexamples_entry", "counterexamples.md")
    return DualLoopPaths(
        unit_root=root,
        unit_config_path=root / UNIT_CONFIG_NAME,
        runs_root=runs_root_for_unit(root),
        current_run_path=current_run_path_for_unit(root),
        run_id=selected_run_id,
        run_root=run_root,
        queue_root=run_root / "queue",
        prompt_path=root / config.prompt_entry,
        yang_seed_path=root / config.yang_entry,
        yin_seed_path=root / config.yin_entry,
        yang_candidate_seed_path=root / yang_candidate_entry,
        yang_witness_seed_path=root / yang_witness_entry,
        yang_derivation_seed_path=root / yang_derivation_entry,
        yin_problem_spec_seed_path=root / yin_problem_spec_entry,
        yin_counterexamples_seed_path=root / yin_counterexamples_entry,
        yang_path=run_root / config.yang_entry,
        yin_path=run_root / config.yin_entry,
        yang_candidate_path=run_root / yang_candidate_entry,
        yang_witness_path=run_root / yang_witness_entry,
        yang_derivation_path=run_root / yang_derivation_entry,
        yin_problem_spec_path=run_root / yin_problem_spec_entry,
        yin_counterexamples_path=run_root / yin_counterexamples_entry,
        yang_scratchpad_path=run_root / "yang_scratchpad.md",
        yin_scratchpad_path=run_root / "yin_scratchpad.md",
        yang_notebook_path=run_root / "yang_notebook.md",
        yin_notebook_path=run_root / "yin_notebook.md",
        workspace_path=run_root / "workspace",
        yang_prompt_path=resolve_prompt_path(root, "yang_prompt.override.md", "yang_prompt.md", prompt_set),
        yin_prompt_path=resolve_prompt_path(root, "yin_prompt.override.md", "yin_prompt.md", prompt_set),
        yin_seed_prompt_path=resolve_prompt_path(root, "yin_seed_prompt.override.md", "yin_seed_prompt.md", prompt_set),
        yang_system_prompt_path=resolve_prompt_path(root, "yang_system_prompt.override.txt", "yang_system_prompt.txt", prompt_set),
        yin_system_prompt_path=resolve_prompt_path(root, "yin_system_prompt.override.txt", "yin_system_prompt.txt", prompt_set),
        world_path=run_root / "world.json",
        law_path=run_root / "law.md",
        law_state_path=run_root / "law_state.json",
        yin_snapshot_path=run_root / "yin.snapshot.py",
        results_path=run_root / "results.json",
        history_path=run_root / "history.ndjson",
        ideas_path=run_root / "ideas.ndjson",
        frontier_path=run_root / "frontier.json",
        config=config,
    )


@contextmanager
def working_directory(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


@contextmanager
def run_environment(paths: DualLoopPaths):
    previous = {
        "TAIJI_UNIT_ROOT": os.environ.get("TAIJI_UNIT_ROOT"),
        "TAIJI_RUN_ROOT": os.environ.get("TAIJI_RUN_ROOT"),
        "TAIJI_WORLD_PATH": os.environ.get("TAIJI_WORLD_PATH"),
        "TAIJI_LAW_PATH": os.environ.get("TAIJI_LAW_PATH"),
        "TAIJI_RESULTS_PATH": os.environ.get("TAIJI_RESULTS_PATH"),
        "TAIJI_HISTORY_PATH": os.environ.get("TAIJI_HISTORY_PATH"),
        "TAIJI_YIN_SNAPSHOT_PATH": os.environ.get("TAIJI_YIN_SNAPSHOT_PATH"),
        "TAIJI_CANDIDATE_PATH": os.environ.get("TAIJI_CANDIDATE_PATH"),
        "TAIJI_WITNESS_PATH": os.environ.get("TAIJI_WITNESS_PATH"),
        "TAIJI_DERIVATION_PATH": os.environ.get("TAIJI_DERIVATION_PATH"),
        "TAIJI_PROBLEM_SPEC_PATH": os.environ.get("TAIJI_PROBLEM_SPEC_PATH"),
        "TAIJI_COUNTEREXAMPLES_PATH": os.environ.get("TAIJI_COUNTEREXAMPLES_PATH"),
    }
    paths.run_root.mkdir(parents=True, exist_ok=True)
    os.environ["TAIJI_UNIT_ROOT"] = str(paths.unit_root)
    os.environ["TAIJI_RUN_ROOT"] = str(paths.run_root)
    os.environ["TAIJI_WORLD_PATH"] = str(paths.world_path)
    os.environ["TAIJI_LAW_PATH"] = str(paths.law_path)
    os.environ["TAIJI_RESULTS_PATH"] = str(paths.results_path)
    os.environ["TAIJI_HISTORY_PATH"] = str(paths.history_path)
    os.environ["TAIJI_YIN_SNAPSHOT_PATH"] = str(paths.yin_snapshot_path)
    os.environ["TAIJI_CANDIDATE_PATH"] = str(paths.yang_candidate_path)
    os.environ["TAIJI_WITNESS_PATH"] = str(paths.yang_witness_path)
    os.environ["TAIJI_DERIVATION_PATH"] = str(paths.yang_derivation_path)
    os.environ["TAIJI_PROBLEM_SPEC_PATH"] = str(paths.yin_problem_spec_path)
    os.environ["TAIJI_COUNTEREXAMPLES_PATH"] = str(paths.yin_counterexamples_path)
    # Add run_root to sys.path so `from workspace.X import Y` works
    run_root_str = str(paths.run_root)
    path_added = run_root_str not in sys.path
    if path_added:
        sys.path.insert(0, run_root_str)
    with working_directory(paths.run_root):
        try:
            yield
        finally:
            if path_added and run_root_str in sys.path:
                sys.path.remove(run_root_str)
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def load_module(path: Path, *, label: str) -> Any:
    source = path.read_text(encoding="utf-8")
    fingerprint = hashlib.sha256(f"{path.resolve()}::{label}::{source}".encode("utf-8")).hexdigest()
    module_name = f"taiji_{path.stem}_{fingerprint}"
    module = types.ModuleType(module_name)
    module.__file__ = str(path)
    code = compile(source, str(path), "exec")
    exec(code, module.__dict__)
    return module


def load_callable(path: Path, attr_name: str, *, label: str | None = None) -> Callable[..., Any]:
    module = load_module(path, label=label or attr_name)
    fn = getattr(module, attr_name, None)
    if not callable(fn):
        raise RuntimeError(f"{path.name} must define callable {attr_name}()")
    return fn


def copy_seed_file(seed_path: Path, work_path: Path) -> None:
    if not seed_path.exists():
        raise RuntimeError(f"Seed file is missing: {seed_path}")
    work_path.parent.mkdir(parents=True, exist_ok=True)
    work_path.write_text(seed_path.read_text(encoding="utf-8"), encoding="utf-8")


def ensure_run_workspace(paths: DualLoopPaths, *, refresh: bool = False) -> None:
    paths.run_root.mkdir(parents=True, exist_ok=True)
    for seed_path, work_path in (
        (paths.yang_seed_path, paths.yang_path),
        (paths.yin_seed_path, paths.yin_path),
        (paths.yang_candidate_seed_path, paths.yang_candidate_path),
        (paths.yang_witness_seed_path, paths.yang_witness_path),
        (paths.yang_derivation_seed_path, paths.yang_derivation_path),
        (paths.yin_problem_spec_seed_path, paths.yin_problem_spec_path),
        (paths.yin_counterexamples_seed_path, paths.yin_counterexamples_path),
    ):
        if not seed_path.exists():
            continue
        if refresh or not work_path.exists():
            copy_seed_file(seed_path, work_path)
    # Create workspace for yang's self-built modules
    paths.workspace_path.mkdir(parents=True, exist_ok=True)
    init_path = paths.workspace_path / "__init__.py"
    if not init_path.exists():
        init_path.write_text("# Yang workspace — importable modules built across iterations\n", encoding="utf-8")
    manifest_path = paths.workspace_path / "manifest.json"
    if not manifest_path.exists():
        write_json(manifest_path, {"modules": {}, "note": "Yang maintains this index of workspace modules."})


def validate_zero_arg_signature(fn: Callable[..., Any], label: str) -> None:
    signature = inspect.signature(fn)
    if len(signature.parameters) != 0:
        raise RuntimeError(f"{label} must not take arguments")


def validate_one_arg_signature(fn: Callable[..., Any], label: str) -> None:
    signature = inspect.signature(fn)
    if len(signature.parameters) != 1:
        raise RuntimeError(f"{label} must take exactly one argument")


def ensure_json_object(name: str, raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise RuntimeError(f"{name} must return dict, got {type(raw).__name__}")
    try:
        json.dumps(raw)
    except TypeError as exc:
        raise RuntimeError(f"{name} returned non-JSON-serializable data: {exc}") from exc
    return dict(raw)


def validate_json_value(name: str, raw: Any) -> None:
    if isinstance(raw, dict):
        for key, value in raw.items():
            if not isinstance(key, str):
                raise RuntimeError(f"{name} must use string keys; got {type(key).__name__}")
            validate_json_value(f"{name}.{key}", value)
        return
    if isinstance(raw, list):
        for index, value in enumerate(raw):
            validate_json_value(f"{name}[{index}]", value)
        return
    if isinstance(raw, (str, int, float, bool)) or raw is None:
        return
    raise RuntimeError(f"{name} has unsupported type {type(raw).__name__}")


def normalize_results(raw: Any) -> JSONObject:
    if not isinstance(raw, dict):
        return {
            "error": f"yang returned {type(raw).__name__}, expected dict",
            "yang_contract_ok": False,
        }
    try:
        validate_json_value("yang submission", raw)
        json.dumps(raw, allow_nan=False)
    except Exception as exc:
        return {
            "error": f"yang contract violation: {exc}",
            "yang_contract_ok": False,
        }
    normalized = dict(raw)
    normalized.setdefault("yang_contract_ok", True)
    return normalized


def append_history(
    paths: DualLoopPaths,
    *,
    phase: str,
    world: dict[str, Any],
    results: JSONObject,
    passed: bool | None,
    score: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record = {
        "timestamp": iso_timestamp_now(),
        "phase": phase,
        "world": world,
        "results": results,
        "passed": passed,
    }
    if score is not None:
        record["score"] = score
    if metadata:
        record.update(metadata)
    append_ndjson(paths.history_path, record)
    return record


def latest_history_entry(paths: DualLoopPaths) -> dict[str, Any] | None:
    if not paths.history_path.exists():
        return None
    lines = [line.strip() for line in paths.history_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        return None
    return json.loads(lines[-1])


YANG_TIMEOUT_SECONDS = 300  # 5 minutes default


def mechanism_search_results(paths: DualLoopPaths, *, persist_results: bool = True) -> JSONObject:
    try:
        candidate = ensure_json_object(
            paths.yang_candidate_path.name,
            json.loads(paths.yang_candidate_path.read_text(encoding="utf-8")),
        )
        witness = ensure_json_object(
            paths.yang_witness_path.name,
            json.loads(paths.yang_witness_path.read_text(encoding="utf-8")),
        )
        derivation = paths.yang_derivation_path.read_text(encoding="utf-8").strip()
        implementation_exists = paths.yang_path.exists()
        results: JSONObject = {
            "candidate": candidate,
            "witness": witness,
            "derivation": derivation,
            "artifacts": {
                "candidate_path": str(paths.yang_candidate_path),
                "witness_path": str(paths.yang_witness_path),
                "derivation_path": str(paths.yang_derivation_path),
                "implementation_path": str(paths.yang_path),
                "implementation_exists": implementation_exists,
            },
            "yang_contract_ok": True,
        }
    except Exception as exc:
        results = {
            "error": f"mechanism artifact invalid: {type(exc).__name__}: {exc}",
            "yang_contract_ok": False,
        }
    if persist_results:
        write_json(paths.results_path, results)
    return results


def run_program_search(paths: DualLoopPaths, *, persist_results: bool = True, timeout: int = YANG_TIMEOUT_SECONDS) -> JSONObject:
    ensure_run_workspace(paths)
    yang = load_callable(paths.yang_path, "run")
    validate_zero_arg_signature(yang, "yang.run()")
    try:
        with run_environment(paths):
            if timeout > 0:
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(yang)
                    try:
                        raw_results = future.result(timeout=timeout)
                    except concurrent.futures.TimeoutError:
                        raw_results = {"error": f"yang.run() timed out after {timeout}s"}
            else:
                raw_results = yang()
    except Exception as exc:
        raw_results = {"error": f"yang crashed: {type(exc).__name__}: {exc}"}
    results = normalize_results(raw_results)
    if persist_results:
        write_json(paths.results_path, results)
    return results


def run_yang(paths: DualLoopPaths, *, persist_results: bool = True, timeout: int = YANG_TIMEOUT_SECONDS) -> JSONObject:
    problem_kind = getattr(paths.config, "problem_kind", "program_search")
    if problem_kind == "mechanism_search":
        ensure_run_workspace(paths)
        return mechanism_search_results(paths, persist_results=persist_results)
    return run_program_search(paths, persist_results=persist_results, timeout=timeout)


def evaluate_yang_trial(
    paths: DualLoopPaths,
    snapshot: LawSnapshot,
    *,
    persist_results: bool = True,
    persist_history: bool = False,
    phase: str = "trial",
) -> dict[str, Any]:
    results = run_yang(paths, persist_results=persist_results)
    passed = evaluate_snapshot(paths, snapshot, results)
    score = score_snapshot(paths, snapshot, results).to_json()
    record = {
        "timestamp": iso_timestamp_now(),
        "phase": phase,
        "world": snapshot.world,
        "results": results,
        "passed": passed,
        "score": score,
        "source_hash": snapshot.source_hash,
    }
    if persist_history:
        append_history(
            paths,
            phase=phase,
            world=snapshot.world,
            results=results,
            passed=passed,
            score=score,
            metadata={"source_hash": snapshot.source_hash},
        )
    return record


def trial_beats(candidate: dict[str, Any], baseline: dict[str, Any] | None) -> bool:
    if baseline is None:
        return bool(candidate.get("passed"))
    candidate_passed = bool(candidate.get("passed"))
    baseline_passed = bool(baseline.get("passed"))
    if candidate_passed != baseline_passed:
        return candidate_passed
    candidate_score = scorecard_from_json(candidate.get("score", {}))
    baseline_score = scorecard_from_json(baseline.get("score", {}))
    return compare_scorecards(candidate_score, baseline_score) > 0


def run_yin_world(paths: DualLoopPaths) -> dict[str, Any]:
    ensure_run_workspace(paths)
    if has_materialized_law(paths):
        return load_materialized_snapshot(paths).world
    return build_law_snapshot(paths, paths.yin_path, label="live-yin-world-only").world


def run_yin_passes(paths: DualLoopPaths, results: JSONObject) -> bool:
    ensure_run_workspace(paths)
    if has_materialized_law(paths):
        snapshot = load_materialized_snapshot(paths)
    else:
        snapshot = build_law_snapshot(paths, paths.yin_path, label="live-yin-pass-only")
    return evaluate_snapshot(paths, snapshot, results)


def validate_yin(paths: DualLoopPaths, probe_results: JSONObject | None = None) -> YinValidation:
    ensure_run_workspace(paths)
    validation = validate_live_yin(paths, probe_results)
    materialize_law_snapshot(paths, validation.snapshot)
    return validation


def seed(paths: DualLoopPaths) -> dict[str, Any]:
    validation = validate_yin(paths)
    return append_history(
        paths,
        phase="seed",
        world=validation.snapshot.world,
        results={},
        passed=None,
        score=validation.probe_score.to_json(),
        metadata={
            "status": "materialized",
            "source_hash": validation.snapshot.source_hash,
        },
    )


def run_round(paths: DualLoopPaths, *, auto_seed: bool = True) -> dict[str, Any]:
    if not has_materialized_law(paths):
        if not auto_seed:
            raise RuntimeError("No materialized law snapshot. Run seed first or omit --no-auto-seed.")
        seed(paths)

    snapshot = load_materialized_snapshot(paths)
    record = evaluate_yang_trial(paths, snapshot, persist_results=True, persist_history=False, phase="round")
    results = record["results"]
    passed = bool(record["passed"])
    write_law(paths, snapshot, passed)
    return append_history(
        paths,
        phase="round",
        world=snapshot.world,
        results=results,
        passed=passed,
        score=record["score"],
        metadata={
            "status": "evaluated",
            "source_hash": snapshot.source_hash,
        },
    )


def status(paths: DualLoopPaths) -> dict[str, Any]:
    entry = latest_history_entry(paths)
    return {
        "unit_root": str(paths.unit_root),
        "unit_config_path": str(paths.unit_config_path),
        "runs_root": str(paths.runs_root),
        "current_run_path": str(paths.current_run_path),
        "run_id": paths.run_id,
        "run_root": str(paths.run_root),
        "queue_root": str(paths.queue_root),
        "prompt_path": str(paths.prompt_path),
        "yang_seed_path": str(paths.yang_seed_path),
        "yin_seed_path": str(paths.yin_seed_path),
        "yang_candidate_seed_path": str(paths.yang_candidate_seed_path),
        "yang_witness_seed_path": str(paths.yang_witness_seed_path),
        "yang_derivation_seed_path": str(paths.yang_derivation_seed_path),
        "yin_problem_spec_seed_path": str(paths.yin_problem_spec_seed_path),
        "yin_counterexamples_seed_path": str(paths.yin_counterexamples_seed_path),
        "yang_path": str(paths.yang_path),
        "yin_path": str(paths.yin_path),
        "yang_candidate_path": str(paths.yang_candidate_path),
        "yang_witness_path": str(paths.yang_witness_path),
        "yang_derivation_path": str(paths.yang_derivation_path),
        "yin_problem_spec_path": str(paths.yin_problem_spec_path),
        "yin_counterexamples_path": str(paths.yin_counterexamples_path),
        "yang_scratchpad_path": str(paths.yang_scratchpad_path),
        "yin_scratchpad_path": str(paths.yin_scratchpad_path),
        "yang_prompt_path": str(paths.yang_prompt_path),
        "yin_prompt_path": str(paths.yin_prompt_path),
        "yin_seed_prompt_path": str(paths.yin_seed_prompt_path),
        "yang_system_prompt_path": str(paths.yang_system_prompt_path),
        "yin_system_prompt_path": str(paths.yin_system_prompt_path),
        "world_path": str(paths.world_path),
        "law_path": str(paths.law_path),
        "law_state_path": str(paths.law_state_path),
        "yin_snapshot_path": str(paths.yin_snapshot_path),
        "results_path": str(paths.results_path),
        "history_path": str(paths.history_path),
        "ideas_path": str(paths.ideas_path),
        "frontier_path": str(paths.frontier_path),
        "config": {
            "name": paths.config.name,
            "kind": paths.config.kind,
            "problem_kind": getattr(paths.config, "problem_kind", "program_search"),
            "prompt_set": paths.config.prompt_set,
            "prompt_entry": paths.config.prompt_entry,
            "yang_entry": paths.config.yang_entry,
            "yin_entry": paths.config.yin_entry,
            "yang_candidate_entry": getattr(paths.config, "yang_candidate_entry", "candidate.json"),
            "yang_witness_entry": getattr(paths.config, "yang_witness_entry", "witness.json"),
            "yang_derivation_entry": getattr(paths.config, "yang_derivation_entry", "derivation.md"),
            "yin_problem_spec_entry": getattr(paths.config, "yin_problem_spec_entry", "problem_spec.md"),
            "yin_counterexamples_entry": getattr(paths.config, "yin_counterexamples_entry", "counterexamples.md"),
        },
        "latest": entry,
    }


def prompt_text_from_args(goal: str | None, prompt_file: Path | None) -> str | None:
    if goal and prompt_file is not None:
        raise RuntimeError("Use either --goal or --prompt-file, not both.")
    if prompt_file is not None:
        return prompt_file.read_text(encoding="utf-8")
    return goal


def add_run_selection_args(parser: argparse.ArgumentParser, *, include_new: bool = True) -> None:
    parser.add_argument("--run-id", type=str, default=None, help="Resume or target a specific run id")
    if include_new:
        parser.add_argument("--new", action="store_true", help="Start a fresh run in a new run folder")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Taiji yin/yang cycle")
    subparsers = parser.add_subparsers(dest="command", required=True)

    new_parser = subparsers.add_parser("new", help="Create a new unit scaffold from a concept")
    new_parser.add_argument("target", help="Unit name under units/ or explicit unit path")
    new_parser.add_argument("--goal", type=str, default=None, help="Goal text written into prompt.md")
    new_parser.add_argument("--prompt-file", type=Path, default=None, help="Read prompt.md content from a file")
    new_parser.add_argument(
        "--problem-kind",
        choices=(DEFAULT_PROBLEM_KIND, MECHANISM_SEARCH_KIND),
        default=DEFAULT_PROBLEM_KIND,
        help="Problem surface to scaffold. mechanism_search creates candidate/witness/derivation artifacts.",
    )
    new_parser.add_argument("--force", action="store_true", help="Overwrite scaffolded files if they already exist")
    new_parser.add_argument("--no-readme", action="store_true", help="Do not create README.md")

    seed_parser = subparsers.add_parser("seed", help="Validate yin and materialize the active world/law snapshot")
    seed_parser.add_argument("--unit-root", type=Path, required=True, help="Unit root")
    add_run_selection_args(seed_parser)
    round_parser = subparsers.add_parser("round", help="Run one yang round against the materialized law snapshot")
    round_parser.add_argument("--unit-root", type=Path, required=True, help="Unit root")
    round_parser.add_argument("--no-auto-seed", action="store_true", help="Do not seed law automatically if missing")
    add_run_selection_args(round_parser)
    status_parser = subparsers.add_parser("status", help="Show current generated artifact paths and latest history entry")
    status_parser.add_argument("--unit-root", type=Path, required=True, help="Unit root")
    add_run_selection_args(status_parser, include_new=False)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "new":
        payload = bootstrap_unit(
            resolve_new_unit_root(args.target),
            prompt_text=prompt_text_from_args(args.goal, args.prompt_file),
            problem_kind=args.problem_kind,
            force=args.force,
            include_readme=not args.no_readme,
            require_prompt=False,
        )
        print(json.dumps(payload, indent=2, sort_keys=False))
        return

    create_run = args.command in {"seed", "round"}
    paths = dual_loop_paths(
        args.unit_root,
        run_id=getattr(args, "run_id", None),
        create_run=create_run,
        new_run=getattr(args, "new", False),
    )

    if args.command in {"seed", "round"}:
        bootstrap_unit(paths.unit_root, include_readme=False, require_prompt=True)
        paths = dual_loop_paths(paths.unit_root, run_id=paths.run_id, create_run=True)

    if args.command == "seed":
        print(json.dumps(seed(paths), indent=2, sort_keys=False))
        return

    if args.command == "round":
        print(json.dumps(run_round(paths, auto_seed=not args.no_auto_seed), indent=2, sort_keys=False))
        return

    print(json.dumps(status(paths), indent=2, sort_keys=False))


if __name__ == "__main__":
    main()
