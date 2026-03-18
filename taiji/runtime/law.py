"""Law snapshot helpers for taiji."""

from __future__ import annotations

import hashlib
import json
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

from .schema import iso_timestamp_now, read_json, write_json

JSONScalar = str | int | float | bool | None
JSONValue = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]
JSONObject = dict[str, JSONValue]


@dataclass(frozen=True)
class LawSnapshot:
    source_path: Path
    source_text: str
    source_hash: str
    world: dict[str, Any]
    passes_fn: Callable[[JSONObject], bool]


@dataclass(frozen=True)
class YinValidation:
    snapshot: LawSnapshot
    probe_results: JSONObject
    probe_passed: bool


@contextmanager
def staged_text_file(path: Path, text: str) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()
    previous_text = path.read_text(encoding="utf-8") if existed else None
    path.write_text(text, encoding="utf-8")
    try:
        yield
    finally:
        if existed:
            path.write_text(previous_text or "", encoding="utf-8")
        else:
            path.unlink(missing_ok=True)


@contextmanager
def staged_snapshot_environment(paths: Any, snapshot: LawSnapshot, *, passed: bool | None = None) -> Iterator[None]:
    with ExitStack() as stack:
        stack.enter_context(staged_text_file(
            paths.world_path,
            json.dumps(snapshot.world, indent=2, sort_keys=False) + "\n",
        ))
        stack.enter_context(staged_text_file(paths.law_path, render_law_markdown(snapshot, passed=passed)))
        yield


def build_law_snapshot(paths: Any, source_path: Path, *, label: str) -> LawSnapshot:
    from .cycle import (
        ensure_json_object,
        load_module,
        run_environment,
        validate_one_arg_signature,
        validate_zero_arg_signature,
    )

    source_text = source_path.read_text(encoding="utf-8")
    source_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    module = load_module(source_path, label=label)
    world_fn = getattr(module, "world", None)
    passes_fn = getattr(module, "passes", None)
    if not callable(world_fn):
        raise RuntimeError(f"{source_path.name} must define callable world()")
    if not callable(passes_fn):
        raise RuntimeError(f"{source_path.name} must define callable passes(results)")
    validate_zero_arg_signature(world_fn, "yin.world()")
    validate_one_arg_signature(passes_fn, "yin.passes(results)")
    with run_environment(paths):
        raw_world = world_fn()
    world = ensure_json_object("yin.world()", raw_world)
    return LawSnapshot(
        source_path=source_path,
        source_text=source_text,
        source_hash=source_hash,
        world=world,
        passes_fn=passes_fn,
    )


def evaluate_snapshot(paths: Any, snapshot: LawSnapshot, results: JSONObject) -> bool:
    from .cycle import run_environment

    with staged_snapshot_environment(paths, snapshot):
        with run_environment(paths):
            raw_passed = snapshot.passes_fn(results)
    if not isinstance(raw_passed, bool):
        raise RuntimeError(f"yin.passes(results) must return bool, got {type(raw_passed).__name__}")
    return raw_passed


def render_law_markdown(snapshot: LawSnapshot, *, passed: bool | None = None) -> str:
    lines = [
        "# Law\n\n",
        "## World Snapshot\n\n",
        "```json\n",
        json.dumps(snapshot.world, indent=2, sort_keys=False),
        "\n```\n\n",
        "## Acceptance Source\n\n",
        f"- source_hash: `{snapshot.source_hash}`\n",
        f"- source_file: `{snapshot.source_path.name}`\n\n",
        "The active law is the exact `passes(results)` implementation in the snapshot below.\n\n",
        "```python\n",
        snapshot.source_text.rstrip(),
        "\n```\n",
    ]
    if passed is not None:
        lines.extend([
            "\n## Last Outcome\n\n",
            f"- passed: `{str(bool(passed)).lower()}`\n",
        ])
    return "".join(lines)


def write_law(paths: Any, snapshot: LawSnapshot, passed: bool | None = None) -> None:
    paths.law_path.parent.mkdir(parents=True, exist_ok=True)
    paths.law_path.write_text(render_law_markdown(snapshot, passed=passed), encoding="utf-8")


def write_law_state(paths: Any, snapshot: LawSnapshot) -> None:
    write_json(paths.law_state_path, {
        "materialized_at": iso_timestamp_now(),
        "source_hash": snapshot.source_hash,
        "source_path": str(snapshot.source_path),
        "world": snapshot.world,
    })


def materialize_law_snapshot(paths: Any, snapshot: LawSnapshot, *, passed: bool | None = None) -> None:
    paths.run_root.mkdir(parents=True, exist_ok=True)
    write_json(paths.world_path, snapshot.world)
    paths.yin_snapshot_path.write_text(snapshot.source_text.rstrip() + "\n", encoding="utf-8")
    write_law_state(paths, snapshot)
    write_law(paths, snapshot, passed=passed)


def has_materialized_law(paths: Any) -> bool:
    return paths.world_path.exists() and paths.law_path.exists() and paths.yin_snapshot_path.exists()


def load_materialized_snapshot(paths: Any) -> LawSnapshot:
    if not has_materialized_law(paths):
        raise RuntimeError("No materialized law snapshot. Run seed first.")
    snapshot = build_law_snapshot(paths, paths.yin_snapshot_path, label="materialized-law")
    stored_world = read_json(paths.world_path)
    if snapshot.world != stored_world:
        raise RuntimeError(
            "Materialized yin snapshot is not stable: re-evaluating yin.snapshot.py produced a different world than world.json. Re-seed yin."
        )
    if paths.law_state_path.exists():
        state = read_json(paths.law_state_path)
        stored_hash = state.get("source_hash")
        if stored_hash and stored_hash != snapshot.source_hash:
            raise RuntimeError("Materialized law snapshot hash does not match law_state.json. Re-seed yin.")
    return LawSnapshot(
        source_path=snapshot.source_path,
        source_text=snapshot.source_text,
        source_hash=snapshot.source_hash,
        world=stored_world,
        passes_fn=snapshot.passes_fn,
    )


def validate_live_yin(paths: Any, probe_results: JSONObject | None = None) -> YinValidation:
    probe = {} if probe_results is None else dict(probe_results)
    primary = build_law_snapshot(paths, paths.yin_path, label="live-yin-primary")
    probe_passed = evaluate_snapshot(paths, primary, probe)

    secondary = build_law_snapshot(paths, paths.yin_path, label="live-yin-secondary")
    secondary_passed = evaluate_snapshot(paths, secondary, probe)

    if primary.world != secondary.world:
        raise RuntimeError(
            "yin.world() must be stable across fresh imports. Materializing the same yin.py twice produced different worlds."
        )
    if probe_passed != secondary_passed:
        raise RuntimeError(
            "yin.passes(results) must be stable across fresh imports after world() has materialized the law."
        )
    return YinValidation(snapshot=primary, probe_results=probe, probe_passed=probe_passed)
