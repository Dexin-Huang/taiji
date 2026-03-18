"""Shared taiji yin/yang cycle.

Each unit owns only its goal and the law/solution pair described by `unit.toml`.
The host stays mechanical: it materializes a law snapshot, runs yang inside that
snapshot, and records the resulting artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import inspect
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .bootstrap import bootstrap_unit, resolve_new_unit_root
from .config import UNIT_CONFIG_NAME, UnitConfig, load_unit_config, resolve_prompt_path
from .law import (
    LawSnapshot,
    YinValidation,
    build_law_snapshot,
    evaluate_snapshot,
    has_materialized_law,
    load_materialized_snapshot,
    materialize_law_snapshot,
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
    run_root: Path
    queue_root: Path
    prompt_path: Path
    yang_path: Path
    yin_path: Path
    yang_scratchpad_path: Path
    yin_scratchpad_path: Path
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


def resolve_run_root(root: Path) -> Path:
    return ROOT / "runs" / run_slug_for_unit(root) / "current"


def dual_loop_paths(unit_root: Path | str) -> DualLoopPaths:
    root = resolve_unit_root(unit_root)
    config = load_unit_config(root)
    run_root = resolve_run_root(root)
    prompt_set = config.prompt_set
    return DualLoopPaths(
        unit_root=root,
        unit_config_path=root / UNIT_CONFIG_NAME,
        run_root=run_root,
        queue_root=run_root / "queue",
        prompt_path=root / config.prompt_entry,
        yang_path=root / config.yang_entry,
        yin_path=root / config.yin_entry,
        yang_scratchpad_path=run_root / "yang_scratchpad.md",
        yin_scratchpad_path=run_root / "yin_scratchpad.md",
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
    }
    paths.run_root.mkdir(parents=True, exist_ok=True)
    os.environ["TAIJI_UNIT_ROOT"] = str(paths.unit_root)
    os.environ["TAIJI_RUN_ROOT"] = str(paths.run_root)
    os.environ["TAIJI_WORLD_PATH"] = str(paths.world_path)
    os.environ["TAIJI_LAW_PATH"] = str(paths.law_path)
    os.environ["TAIJI_RESULTS_PATH"] = str(paths.results_path)
    os.environ["TAIJI_HISTORY_PATH"] = str(paths.history_path)
    os.environ["TAIJI_YIN_SNAPSHOT_PATH"] = str(paths.yin_snapshot_path)
    with working_directory(paths.run_root):
        try:
            yield
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def load_module(path: Path, *, label: str) -> Any:
    source = path.read_text(encoding="utf-8")
    fingerprint = hashlib.sha256(f"{path.resolve()}::{label}::{source}".encode("utf-8")).hexdigest()
    module_name = f"taiji_{path.stem}_{fingerprint}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_callable(path: Path, attr_name: str, *, label: str | None = None) -> Callable[..., Any]:
    module = load_module(path, label=label or attr_name)
    fn = getattr(module, attr_name, None)
    if not callable(fn):
        raise RuntimeError(f"{path.name} must define callable {attr_name}()")
    return fn


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
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record = {
        "timestamp": iso_timestamp_now(),
        "phase": phase,
        "world": world,
        "results": results,
        "passed": passed,
    }
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


def run_yang(paths: DualLoopPaths) -> JSONObject:
    yang = load_callable(paths.yang_path, "run")
    validate_zero_arg_signature(yang, "yang.run()")
    try:
        with run_environment(paths):
            raw_results = yang()
    except Exception as exc:
        raw_results = {"error": f"yang crashed: {type(exc).__name__}: {exc}"}
    results = normalize_results(raw_results)
    write_json(paths.results_path, results)
    return results


def run_yin_world(paths: DualLoopPaths) -> dict[str, Any]:
    if has_materialized_law(paths):
        return load_materialized_snapshot(paths).world
    return build_law_snapshot(paths, paths.yin_path, label="live-yin-world-only").world


def run_yin_passes(paths: DualLoopPaths, results: JSONObject) -> bool:
    if has_materialized_law(paths):
        snapshot = load_materialized_snapshot(paths)
    else:
        snapshot = build_law_snapshot(paths, paths.yin_path, label="live-yin-pass-only")
    return evaluate_snapshot(paths, snapshot, results)


def validate_yin(paths: DualLoopPaths, probe_results: JSONObject | None = None) -> YinValidation:
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
    results = run_yang(paths)
    passed = evaluate_snapshot(paths, snapshot, results)
    write_law(paths, snapshot, passed)
    return append_history(
        paths,
        phase="round",
        world=snapshot.world,
        results=results,
        passed=passed,
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
        "run_root": str(paths.run_root),
        "queue_root": str(paths.queue_root),
        "prompt_path": str(paths.prompt_path),
        "yang_path": str(paths.yang_path),
        "yin_path": str(paths.yin_path),
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
            "prompt_set": paths.config.prompt_set,
            "prompt_entry": paths.config.prompt_entry,
            "yang_entry": paths.config.yang_entry,
            "yin_entry": paths.config.yin_entry,
        },
        "latest": entry,
    }


def prompt_text_from_args(goal: str | None, prompt_file: Path | None) -> str | None:
    if goal and prompt_file is not None:
        raise RuntimeError("Use either --goal or --prompt-file, not both.")
    if prompt_file is not None:
        return prompt_file.read_text(encoding="utf-8")
    return goal


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Taiji yin/yang cycle")
    subparsers = parser.add_subparsers(dest="command", required=True)

    new_parser = subparsers.add_parser("new", help="Create a new unit scaffold from a concept")
    new_parser.add_argument("target", help="Unit name under units/ or explicit unit path")
    new_parser.add_argument("--goal", type=str, default=None, help="Goal text written into prompt.md")
    new_parser.add_argument("--prompt-file", type=Path, default=None, help="Read prompt.md content from a file")
    new_parser.add_argument("--force", action="store_true", help="Overwrite scaffolded files if they already exist")
    new_parser.add_argument("--no-readme", action="store_true", help="Do not create README.md")

    seed_parser = subparsers.add_parser("seed", help="Validate yin and materialize the active world/law snapshot")
    seed_parser.add_argument("--unit-root", type=Path, required=True, help="Unit root")
    round_parser = subparsers.add_parser("round", help="Run one yang round against the materialized law snapshot")
    round_parser.add_argument("--unit-root", type=Path, required=True, help="Unit root")
    round_parser.add_argument("--no-auto-seed", action="store_true", help="Do not seed law automatically if missing")
    status_parser = subparsers.add_parser("status", help="Show current generated artifact paths and latest history entry")
    status_parser.add_argument("--unit-root", type=Path, required=True, help="Unit root")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "new":
        payload = bootstrap_unit(
            resolve_new_unit_root(args.target),
            prompt_text=prompt_text_from_args(args.goal, args.prompt_file),
            force=args.force,
            include_readme=not args.no_readme,
            require_prompt=False,
        )
        print(json.dumps(payload, indent=2, sort_keys=False))
        return

    paths = dual_loop_paths(args.unit_root)

    if args.command in {"seed", "round"}:
        bootstrap_unit(paths.unit_root, include_readme=False, require_prompt=True)
        paths = dual_loop_paths(paths.unit_root)

    if args.command == "seed":
        print(json.dumps(seed(paths), indent=2, sort_keys=False))
        return

    if args.command == "round":
        print(json.dumps(run_round(paths, auto_seed=not args.no_auto_seed), indent=2, sort_keys=False))
        return

    print(json.dumps(status(paths), indent=2, sort_keys=False))


if __name__ == "__main__":
    main()
