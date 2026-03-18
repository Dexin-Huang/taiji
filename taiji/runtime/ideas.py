"""Idea tracking and frontier materialization for the taiji loop."""

from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

from .schema import append_ndjson, read_ndjson, write_json
from .prompts import relative_artifact_path, summarize_response


def infer_tags(*texts: str) -> list[str]:
    haystack = " ".join(texts).lower()
    keyword_map = {
        "recurrent": ["recurrent", "rnn", "gru", "lstm"],
        "state": ["state", "hidden state", "carry"],
        "replay": ["replay", "buffer"],
        "sgd": ["sgd", "gradient", "optimizer", "adam"],
        "linear": ["linear", "matrix", "low-rank", "latent linear"],
        "attention": ["attention", "transformer"],
        "memory": ["memory", "cache"],
        "world": ["world", "environment", "dynamics"],
        "transfer": ["transfer", "held-out", "generalization"],
        "stability": ["stable", "stability", "blow up", "explode", "grad norm"],
        "simplicity": ["simple", "simpler", "minimal", "delete"],
    }
    return sorted({tag for tag, keywords in keyword_map.items() if any(kw in haystack for kw in keywords)})


def idea_parent_ids(paths: Any, *, agent: str) -> list[str]:
    records = read_ndjson(paths.ideas_path)
    parents: list[str] = []
    for record in reversed(records):
        if record.get("agent") == agent:
            parents.append(str(record["id"]))
            break
    opposite = "yin" if agent == "yang" else "yang"
    for record in reversed(records):
        if record.get("agent") == opposite:
            parents.append(str(record["id"]))
            break
    return parents


def append_idea_record(paths: Any, record: dict[str, Any]) -> None:
    existing = read_ndjson(paths.ideas_path)
    if any(item.get("id") == record.get("id") for item in existing):
        return
    append_ndjson(paths.ideas_path, record)


def compact_idea_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": record.get("id"),
        "agent": record.get("agent"),
        "iteration": record.get("iteration"),
        "phase": record.get("phase"),
        "status": record.get("status"),
        "summary": record.get("summary"),
        "tags": record.get("tags", []),
        "artifact_dir": record.get("artifact_dir"),
        "parent_ids": record.get("parent_ids", []),
    }


def materialize_frontier(paths: Any) -> None:
    records = read_ndjson(paths.ideas_path)
    latest = records[-1] if records else None
    latest_yang = next((r for r in reversed(records) if r.get("agent") == "yang"), None)
    latest_yin = next((r for r in reversed(records) if r.get("agent") == "yin"), None)
    failed_yang = [r for r in records if r.get("agent") == "yang" and r.get("status") == "failed"]
    tag_counts = Counter(tag for r in records for tag in r.get("tags", []))
    write_json(paths.frontier_path, {
        "latest": compact_idea_record(latest) if latest else None,
        "latest_yang": compact_idea_record(latest_yang) if latest_yang else None,
        "latest_yin": compact_idea_record(latest_yin) if latest_yin else None,
        "recent": [compact_idea_record(r) for r in records[-10:]],
        "open_failed_ideas": [compact_idea_record(r) for r in failed_yang[-10:]],
        "tag_counts": dict(sorted(tag_counts.items())),
    })


def record_seed_idea(
    paths: Any, root: Path, *, artifact_dir: Path, response: str, changed: bool, world: dict[str, Any],
) -> None:
    record = {
        "id": "yin-seed",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "agent": "yin",
        "phase": "seed",
        "iteration": 0,
        "status": "seeded",
        "summary": summarize_response(response, "Seeded the initial world and pass condition."),
        "tags": infer_tags(response, json.dumps(world, sort_keys=True)),
        "parent_ids": [],
        "artifact_dir": relative_artifact_path(artifact_dir, root),
        "changed": changed,
        "world_keys": sorted(world.keys()),
    }
    append_idea_record(paths, record)
    materialize_frontier(paths)


def record_yang_idea(
    paths: Any,
    root: Path,
    *,
    iteration: int,
    artifact_dir: Path,
    response: str,
    after_text: str,
    record: dict[str, Any],
) -> None:
    passed = bool(record.get("passed"))
    idea = {
        "id": f"yang-{iteration:06d}",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "agent": "yang",
        "phase": "trial",
        "iteration": iteration,
        "status": "passed" if passed else "failed",
        "summary": summarize_response(response, "Yang ran a trial."),
        "tags": infer_tags(response, after_text),
        "parent_ids": idea_parent_ids(paths, agent="yang"),
        "artifact_dir": relative_artifact_path(artifact_dir, root),
        "passed": passed,
        "results": record.get("results", {}),
    }
    append_idea_record(paths, idea)
    materialize_frontier(paths)


def record_yin_idea(
    paths: Any,
    root: Path,
    *,
    iteration: int,
    artifact_dir: Path,
    response: str,
    after_text: str,
    yin_changed: bool,
    world_changed: bool,
    results: dict[str, Any],
    status: str | None = None,
) -> None:
    idea = {
        "id": f"yin-{iteration:06d}",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "agent": "yin",
        "phase": "adaptive",
        "iteration": iteration,
        "status": status or ("applied" if yin_changed or world_changed else "no_change"),
        "summary": summarize_response(response, "Yin reviewed the passing solution."),
        "tags": infer_tags(response, after_text),
        "parent_ids": idea_parent_ids(paths, agent="yin"),
        "artifact_dir": relative_artifact_path(artifact_dir, root),
        "yin_changed": yin_changed,
        "world_changed": world_changed,
        "results": results,
    }
    append_idea_record(paths, idea)
    materialize_frontier(paths)
