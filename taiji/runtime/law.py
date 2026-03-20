"""Law snapshot helpers for taiji."""

from __future__ import annotations

import hashlib
import json
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Literal

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
    score_fn: Callable[[JSONObject], Any] | None


ScoreDirection = Literal["min", "max"]


@dataclass(frozen=True)
class ScoreMetric:
    name: str
    value: float
    direction: ScoreDirection


@dataclass(frozen=True)
class Scorecard:
    order: tuple[ScoreMetric, ...]
    summary: JSONObject

    def to_json(self) -> dict[str, Any]:
        return {
            "order": [
                {"name": metric.name, "value": metric.value, "direction": metric.direction}
                for metric in self.order
            ],
            "summary": dict(self.summary),
        }


@dataclass(frozen=True)
class YinValidation:
    snapshot: LawSnapshot
    probe_results: JSONObject
    probe_passed: bool
    probe_score: Scorecard


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
    score_fn = getattr(module, "score", None)
    if not callable(world_fn):
        raise RuntimeError(f"{source_path.name} must define callable world()")
    if not callable(passes_fn):
        raise RuntimeError(f"{source_path.name} must define callable passes(results)")
    if score_fn is not None and not callable(score_fn):
        raise RuntimeError(f"{source_path.name} score must be callable when defined")
    validate_zero_arg_signature(world_fn, "yin.world()")
    validate_one_arg_signature(passes_fn, "yin.passes(results)")
    if score_fn is not None:
        validate_one_arg_signature(score_fn, "yin.score(results)")
    with run_environment(paths):
        raw_world = world_fn()
    world = ensure_json_object("yin.world()", raw_world)
    return LawSnapshot(
        source_path=source_path,
        source_text=source_text,
        source_hash=source_hash,
        world=world,
        passes_fn=passes_fn,
        score_fn=score_fn,
    )


def evaluate_snapshot(paths: Any, snapshot: LawSnapshot, results: JSONObject) -> bool:
    from .cycle import run_environment

    with staged_snapshot_environment(paths, snapshot):
        with run_environment(paths):
            raw_passed = snapshot.passes_fn(results)
    if not isinstance(raw_passed, bool):
        raise RuntimeError(f"yin.passes(results) must return bool, got {type(raw_passed).__name__}")
    return raw_passed


def normalize_scorecard(raw: Any) -> Scorecard:
    if raw is None:
        return Scorecard(order=(), summary={})
    if not isinstance(raw, dict):
        raise RuntimeError(f"yin.score(results) must return dict, got {type(raw).__name__}")
    summary_raw = raw.get("summary", {})
    if not isinstance(summary_raw, dict):
        raise RuntimeError("yin.score(results) summary must be a dict")
    try:
        json.dumps(summary_raw, allow_nan=False)
    except TypeError as exc:
        raise RuntimeError(f"yin.score(results) summary must be JSON-serializable: {exc}") from exc
    order_raw = raw.get("order", [])
    if not isinstance(order_raw, list):
        raise RuntimeError("yin.score(results) order must be a list")
    order: list[ScoreMetric] = []
    for index, item in enumerate(order_raw):
        if not isinstance(item, dict):
            raise RuntimeError(f"yin.score(results) order[{index}] must be a dict")
        name = item.get("name")
        direction = item.get("direction")
        value = item.get("value")
        if not isinstance(name, str) or not name.strip():
            raise RuntimeError(f"yin.score(results) order[{index}] must have a non-empty string name")
        if direction not in {"min", "max"}:
            raise RuntimeError(f"yin.score(results) order[{index}] direction must be 'min' or 'max'")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise RuntimeError(f"yin.score(results) order[{index}] value must be numeric")
        if value != value or value in {float("inf"), float("-inf")}:
            raise RuntimeError(f"yin.score(results) order[{index}] value must be finite")
        order.append(ScoreMetric(name=name, value=float(value), direction=direction))
    return Scorecard(order=tuple(order), summary=dict(summary_raw))


def score_snapshot(paths: Any, snapshot: LawSnapshot, results: JSONObject) -> Scorecard:
    from .cycle import run_environment

    if snapshot.score_fn is None:
        return Scorecard(order=(), summary={})
    with staged_snapshot_environment(paths, snapshot):
        with run_environment(paths):
            raw_score = snapshot.score_fn(results)
    return normalize_scorecard(raw_score)


def scorecard_from_json(raw: Any) -> Scorecard:
    return normalize_scorecard(raw)


def compare_scorecards(candidate: Scorecard, baseline: Scorecard) -> int:
    if len(candidate.order) != len(baseline.order):
        raise RuntimeError("yin.score(results) changed the number of ordered metrics within one frozen law.")
    for index, (cand_metric, base_metric) in enumerate(zip(candidate.order, baseline.order, strict=True)):
        if cand_metric.name != base_metric.name or cand_metric.direction != base_metric.direction:
            raise RuntimeError(
                "yin.score(results) changed the ordered metric schema within one frozen law "
                f"at position {index}: {cand_metric.name}/{cand_metric.direction} vs {base_metric.name}/{base_metric.direction}."
            )
        delta = cand_metric.value - base_metric.value
        if abs(delta) <= 1e-12:
            continue
        if cand_metric.direction == "max":
            return 1 if cand_metric.value > base_metric.value else -1
        return 1 if cand_metric.value < base_metric.value else -1
    return 0


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
        "The active law is the exact `passes(results)` implementation below.\n",
        "If `score(results)` is defined, the host also uses that exact function as the public progress comparator.\n\n",
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
        "score_defined": snapshot.score_fn is not None,
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
        score_fn=snapshot.score_fn,
    )


def validate_live_yin(paths: Any, probe_results: JSONObject | None = None) -> YinValidation:
    probe = {} if probe_results is None else dict(probe_results)
    primary = build_law_snapshot(paths, paths.yin_path, label="live-yin-primary")
    probe_passed = evaluate_snapshot(paths, primary, probe)
    try:
        probe_score = score_snapshot(paths, primary, probe)
    except Exception as exc:
        raise RuntimeError(
            "yin.score(results) must stay finite on validation probes, including empty, partial, or failed results: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    secondary = build_law_snapshot(paths, paths.yin_path, label="live-yin-secondary")
    secondary_passed = evaluate_snapshot(paths, secondary, probe)
    try:
        secondary_score = score_snapshot(paths, secondary, probe)
    except Exception as exc:
        raise RuntimeError(
            "yin.score(results) must stay finite on validation probes, including empty, partial, or failed results: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    if primary.world != secondary.world:
        raise RuntimeError(
            "yin.world() must be stable across fresh imports. Materializing the same yin.py twice produced different worlds."
        )
    if probe_passed != secondary_passed:
        raise RuntimeError(
            "yin.passes(results) must be stable across fresh imports after world() has materialized the law."
        )
    if probe_score.to_json() != secondary_score.to_json():
        raise RuntimeError(
            "yin.score(results) must be stable across fresh imports after world() has materialized the law."
        )
    return YinValidation(
        snapshot=primary,
        probe_results=probe,
        probe_passed=probe_passed,
        probe_score=probe_score,
    )
