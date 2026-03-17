"""
Claude Agent SDK runner for taiji yin/yang units.

The shared host stays fixed and exposes one immutable executor:
- yang edits yang.py
- yin edits yin.py

Yang owns the search loop. Yin only wakes after a pass.
"""

from __future__ import annotations

import argparse
from collections import Counter
import difflib
import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import anyio

from .cycle import append_history, dual_loop_paths, run_yang, run_yin_passes, run_yin_world, validate_yin
from .schema import ROOT, append_ndjson, read_ndjson, write_json

DEFAULT_AGENT_TOOLS = [
    "Read",
    "Glob",
    "Grep",
    "Write",
    "Edit",
    "MultiEdit",
    "WebFetch",
    "Task",
]
from .sdk_loader import claude_sdk_reference_root, load_claude_agent_sdk


@dataclass
class DualLoopState:
    iteration: int = 0
    yang_session_id: str | None = None
    last_phase: str | None = None
    last_passed: bool | None = None


@dataclass
class YangCycleState:
    paths: Any
    max_calls: int
    world: dict[str, Any]
    artifact_dir: Path | None = None
    calls: int = 0
    last_record: dict[str, Any] | None = None

    async def run(self, note: str) -> dict[str, Any]:
        if self.calls >= self.max_calls:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": "run_cycle call limit reached for this turn. Summarize and stop.",
                    }
                ]
            }

        self.calls += 1
        results = run_yang(self.paths)
        passed = run_yin_passes(self.paths, results)
        record = append_history(
            self.paths,
            phase="trial",
            world=self.world,
            results=results,
            passed=passed,
        )
        self.last_record = record
        payload = {
            "note": note,
            "passed": passed,
            "world": self.world,
            "results": results,
        }
        if self.artifact_dir is not None:
            cycle_dir = self.artifact_dir / "run_cycle"
            cycle_dir.mkdir(parents=True, exist_ok=True)
            write_json(
                cycle_dir / f"call-{self.calls:02d}.json",
                {
                    "call": self.calls,
                    "note": note,
                    "record": record,
                    "payload": payload,
                },
            )
        return {"content": [{"type": "text", "text": json.dumps(payload, indent=2, sort_keys=False)}]}


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="backslashreplace")


def load_state(path: Path) -> DualLoopState:
    if not path.exists():
        return DualLoopState()
    payload = json.loads(path.read_text(encoding="utf-8"))
    return DualLoopState(**payload)


def save_state(path: Path, state: DualLoopState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, asdict(state))


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def ensure_text_file(path: Path, initial_text: str = "") -> None:
    if path.exists():
        return
    write_text(path, initial_text)


def write_diff(path: Path, before: str, after: str, *, fromfile: str, tofile: str) -> None:
    diff = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=fromfile,
            tofile=tofile,
        )
    )
    if not diff:
        diff = "No changes.\n"
    write_text(path, diff)


def artifact_dir(queue_root: Path, label: str) -> Path:
    directory = queue_root / "iterations" / label
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def agent_artifact_dir(iter_dir: Path, agent: str) -> Path:
    directory = iter_dir / agent
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def begin_agent_turn_logging(
    *,
    agent_dir: Path,
    file_label: str,
    prompt: str,
    system_prompt: str,
    before_text: str,
    resumed_session_id: str | None,
) -> None:
    write_text(agent_dir / "prompt.txt", prompt)
    write_text(agent_dir / "system_prompt.txt", system_prompt)
    write_text(agent_dir / f"{file_label}.before.py", before_text)
    write_text(agent_dir / "response.md", "")
    write_json(
        agent_dir / "turn.json",
        {
            "resumed_session_id": resumed_session_id,
            "status": "running",
        },
    )


def finish_agent_turn_logging(
    *,
    agent_dir: Path,
    file_label: str,
    response: str,
    before_text: str,
    after_text: str,
    session_id: str | None,
    resumed_session_id: str | None,
) -> None:
    write_text(agent_dir / "response.md", response or "")
    write_text(agent_dir / f"{file_label}.after.py", after_text)
    write_diff(
        agent_dir / f"{file_label}.diff.patch",
        before_text,
        after_text,
        fromfile=f"{file_label}.before.py",
        tofile=f"{file_label}.after.py",
    )
    write_json(
        agent_dir / "turn.json",
        {
            "session_id": session_id,
            "resumed_session_id": resumed_session_id,
            "changed": before_text != after_text,
            "status": "completed",
        },
    )


def write_iteration_summary(iter_dir: Path, payload: dict[str, Any]) -> None:
    write_json(iter_dir / "summary.json", payload)


def relative_artifact_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def summarize_response(text: str, fallback: str) -> str:
    for raw_line in text.splitlines():
        line = raw_line.strip().lstrip("-*# ").strip()
        if not line:
            continue
        return re.sub(r"\s+", " ", line)[:240]
    return fallback


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
    tags = [tag for tag, keywords in keyword_map.items() if any(keyword in haystack for keyword in keywords)]
    return sorted(set(tags))


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
    latest_yang = next((record for record in reversed(records) if record.get("agent") == "yang"), None)
    latest_yin = next((record for record in reversed(records) if record.get("agent") == "yin"), None)
    failed_yang = [record for record in records if record.get("agent") == "yang" and record.get("status") == "failed"]
    tag_counts = Counter(tag for record in records for tag in record.get("tags", []))
    payload = {
        "latest": compact_idea_record(latest) if latest else None,
        "latest_yang": compact_idea_record(latest_yang) if latest_yang else None,
        "latest_yin": compact_idea_record(latest_yin) if latest_yin else None,
        "recent": [compact_idea_record(record) for record in records[-10:]],
        "open_failed_ideas": [compact_idea_record(record) for record in failed_yang[-10:]],
        "tag_counts": dict(sorted(tag_counts.items())),
    }
    write_json(paths.frontier_path, payload)


def record_seed_idea(paths: Any, *, artifact_dir: Path, response: str, changed: bool, world: dict[str, Any]) -> None:
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
        "artifact_dir": relative_artifact_path(artifact_dir),
        "changed": changed,
        "world_keys": sorted(world.keys()),
    }
    append_idea_record(paths, record)
    materialize_frontier(paths)


def record_yang_idea(
    paths: Any,
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
        "artifact_dir": relative_artifact_path(artifact_dir),
        "passed": passed,
        "results": record.get("results", {}),
    }
    append_idea_record(paths, idea)
    materialize_frontier(paths)


def record_yin_idea(
    paths: Any,
    *,
    iteration: int,
    artifact_dir: Path,
    response: str,
    after_text: str,
    yin_changed: bool,
    world_changed: bool,
    results: dict[str, Any],
) -> None:
    status = "applied" if yin_changed or world_changed else "no_change"
    idea = {
        "id": f"yin-{iteration:06d}",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "agent": "yin",
        "phase": "ratchet",
        "iteration": iteration,
        "status": status,
        "summary": summarize_response(response, "Yin reviewed the passing solution."),
        "tags": infer_tags(response, after_text),
        "parent_ids": idea_parent_ids(paths, agent="yin"),
        "artifact_dir": relative_artifact_path(artifact_dir),
        "yin_changed": yin_changed,
        "world_changed": world_changed,
        "results": results,
    }
    append_idea_record(paths, idea)
    materialize_frontier(paths)


def resolve_edit_path(raw_path: str, cwd: Path, repo_root: Path) -> Path:
    normalized = raw_path.replace("\\", "/")
    if normalized == "/workspace" or normalized.startswith("/workspace/"):
        suffix = normalized.removeprefix("/workspace").lstrip("/")
        return (repo_root / suffix).resolve()
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = cwd / candidate
    return candidate.resolve()


def session_slug(path: Path) -> str:
    try:
        relative = path.relative_to(ROOT).as_posix()
    except ValueError:
        relative = path.name
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", relative.strip("/"))
    return slug or "unit"


def history_summary(paths: Any, limit: int = 6) -> str:
    if not paths.history_path.exists():
        return "No history yet."
    lines = [line.strip() for line in paths.history_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        return "No history yet."
    payloads = [json.loads(line) for line in lines[-limit:]]
    rendered: list[str] = []
    for item in payloads:
        rendered.append(
            f"- phase={item.get('phase')} passed={item.get('passed')} "
            f"world_keys={len(item.get('world', {}))} result_keys={len(item.get('results', {}))}"
        )
    return "\n".join(rendered)


def law_text(paths: Any) -> str:
    if not paths.law_path.exists():
        return "No law yet."
    return paths.law_path.read_text(encoding="utf-8").strip()


def prompt_text(paths: Any) -> str:
    return paths.prompt_path.read_text(encoding="utf-8").strip()


def latest_results(paths: Any) -> str:
    if not paths.results_path.exists():
        return "{}"
    return paths.results_path.read_text(encoding="utf-8").strip()


def latest_world(paths: Any) -> str:
    if not paths.world_path.exists():
        return "{}"
    return paths.world_path.read_text(encoding="utf-8").strip()


def default_yang_prompt_template() -> str:
    return (
        "Yang iteration {iteration}\n\n"
        "You own only {yang_file}.\n"
        "Do not edit {yin_file}, prompt.md, world.json, law.md, results.json, or history.ndjson.\n"
        "Use the immutable run_cycle tool to execute yang inside the current world created by yin.\n"
        "run_cycle is the only source of truth about whether the current yang passes yin's current acceptance condition.\n"
        "If run_cycle returns passed=false, keep editing {yang_file} and call run_cycle again.\n"
        "If run_cycle returns passed=true, stop immediately so yin can wake.\n"
        "Do not stop just because one attempt failed. This loop continues until interrupted.\n"
        "If you hit the run_cycle call limit for this turn, summarize briefly and wait to be resumed.\n\n"
        "Goal:\n"
        "{goal}\n\n"
        "Current public law:\n"
        "{law}\n\n"
        "Current world:\n"
        "{world}\n\n"
        "Recent history:\n"
        "{history}\n\n"
        "End with 2-5 short lines: hypothesis, what changed, and whether the latest yang passed."
    )


def default_yin_seed_prompt_template() -> str:
    return (
        "You are yin. You own only {yin_file}.\n"
        "Write or refine the initial world() and passes(results).\n"
        "Do not edit {yang_file}, prompt.md, world.json, law.md, results.json, or history.ndjson.\n"
        "Preserve both signatures exactly.\n\n"
        "Seed goal:\n"
        "{goal}\n\n"
        "There are no results yet. Establish the first world and first acceptance condition."
    )


def default_yin_prompt_template() -> str:
    return (
        "Yin iteration {iteration}\n\n"
        "You own only {yin_file}. Refine world() and/or passes(results), then stop.\n"
        "Do not edit {yang_file}, prompt.md, world.json, law.md, results.json, or history.ndjson.\n"
        "Preserve both signatures exactly.\n\n"
        "You were only woken because yang satisfied the current world and acceptance condition.\n"
        "Your job is to make the world more real or the pass condition stricter, not to restate the same law.\n\n"
        "Goal:\n"
        "{goal}\n\n"
        "Current public law:\n"
        "{law}\n\n"
        "Current world:\n"
        "{world}\n\n"
        "Latest yang results:\n"
        "{results}\n\n"
        "Recent history:\n"
        "{history}\n\n"
        "Ask: what can this yang still do that it should not be able to do? "
        "If you find a principled gap, encode it by changing world() and/or passes(results)."
    )


class SafePromptDict(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def prompt_context(paths: Any, *, iteration: int | None = None) -> dict[str, str]:
    return {
        "iteration": "" if iteration is None else str(iteration),
        "goal": prompt_text(paths),
        "law": law_text(paths),
        "world": latest_world(paths),
        "results": latest_results(paths),
        "history": history_summary(paths),
        "yang_file": relative_artifact_path(paths.yang_path),
        "yin_file": relative_artifact_path(paths.yin_path),
        "yang_scratchpad": relative_artifact_path(paths.yang_scratchpad_path),
        "yin_scratchpad": relative_artifact_path(paths.yin_scratchpad_path),
        "world_file": relative_artifact_path(paths.world_path),
        "law_file": relative_artifact_path(paths.law_path),
        "results_file": relative_artifact_path(paths.results_path),
        "history_file": relative_artifact_path(paths.history_path),
        "unit_root": relative_artifact_path(paths.unit_root),
        "run_root": relative_artifact_path(paths.run_root),
    }


def render_prompt_template(path: Path, default_template: str, context: dict[str, str]) -> str:
    template = read_text(path) if path.exists() else default_template
    return template.format_map(SafePromptDict(context)).strip()


def render_system_prompt(path: Path, default_prompt: str, context: dict[str, str]) -> str:
    template = read_text(path) if path.exists() else default_prompt
    return template.format_map(SafePromptDict(context)).strip()


def yang_turn_prompt(paths: Any, iteration: int) -> str:
    return render_prompt_template(
        paths.yang_prompt_path,
        default_yang_prompt_template(),
        prompt_context(paths, iteration=iteration),
    )


def yin_seed_prompt(paths: Any) -> str:
    return render_prompt_template(
        paths.yin_seed_prompt_path,
        default_yin_seed_prompt_template(),
        prompt_context(paths),
    )


def yin_turn_prompt(paths: Any, iteration: int) -> str:
    return render_prompt_template(
        paths.yin_prompt_path,
        default_yin_prompt_template(),
        prompt_context(paths, iteration=iteration),
    )


async def run_agent_turn(
    *,
    sdk: Any,
    cwd: Path,
    repo_root: Path,
    editable_paths: list[Path],
    prompt: str,
    system_prompt: str,
    max_turns: int,
    cli_path: str | None,
    claude_model: str | None,
    claude_home: Path,
    resume_session_id: str | None = None,
    session_id: str | None = None,
    mcp_servers: dict[str, Any] | None = None,
    tools: list[str] | None = None,
    allowed_tools: list[str] | None = None,
) -> tuple[str | None, str]:
    claude_home.mkdir(parents=True, exist_ok=True)
    editable_set = {path.resolve() for path in editable_paths}

    async def restrict_edits(input_data: dict[str, Any], tool_use_id: str | None, context: dict[str, Any]) -> dict[str, Any]:
        tool_name = input_data.get("tool_name")
        if tool_name not in {"Write", "Edit", "MultiEdit"}:
            return {}
        raw_path = input_data.get("tool_input", {}).get("file_path")
        if not raw_path:
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "Missing file_path on edit request.",
                }
            }
        target = resolve_edit_path(str(raw_path), cwd, repo_root)
        if target not in editable_set:
            owned = ", ".join(sorted(path.name for path in editable_set))
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": f"Only {owned} may be edited in this turn.",
                }
            }
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "permissionDecisionReason": "Edit stays inside the owned file.",
            }
        }

    options = sdk.ClaudeAgentOptions(
        cwd=str(cwd),
        add_dirs=[repo_root, cwd],
        system_prompt=system_prompt,
        tools=tools or DEFAULT_AGENT_TOOLS,
        allowed_tools=allowed_tools or DEFAULT_AGENT_TOOLS,
        permission_mode="acceptEdits",
        hooks={"PreToolUse": [sdk.HookMatcher(matcher="Write|Edit|MultiEdit", hooks=[restrict_edits])]},
        max_turns=max_turns,
        model=claude_model,
        cli_path=cli_path,
        resume=resume_session_id,
        continue_conversation=resume_session_id is not None,
        mcp_servers=mcp_servers,
        env={
            "HOME": str(claude_home),
            "XDG_CONFIG_HOME": str(claude_home / "config"),
            "XDG_CACHE_HOME": str(claude_home / "cache"),
        },
    )

    assistant_lines: list[str] = []
    final_session_id: str | None = None
    async with sdk.ClaudeSDKClient(options=options) as client:
        await client.query(prompt, session_id=session_id)
        async for message in client.receive_response():
            if isinstance(message, sdk.AssistantMessage):
                for block in message.content:
                    if isinstance(block, sdk.TextBlock):
                        text = block.text.strip()
                        if text:
                            assistant_lines.append(text)
            elif isinstance(message, sdk.ResultMessage):
                final_session_id = message.session_id
    return final_session_id, "\n".join(assistant_lines).strip()


async def run_loop(args: argparse.Namespace) -> None:
    paths = dual_loop_paths(args.unit_root)
    queue_root = paths.queue_root
    queue_root.mkdir(parents=True, exist_ok=True)
    state = load_state(args.state_path)
    sdk = load_claude_agent_sdk()

    slug = session_slug(paths.unit_root)
    yang_session_name = f"taiji-yang-{slug}"
    yin_session_name = f"taiji-yin-{slug}"
    yang_home = args.yang_claude_home or (queue_root / "yang-claude-home")
    yin_home = args.yin_claude_home or (queue_root / "yin-claude-home")
    started_at = time.monotonic()

    sdk_source = claude_sdk_reference_root() if claude_sdk_reference_root().exists() else "installed package"
    print(f"SDK source: {sdk_source}")
    print(f"Unit root: {paths.unit_root}")
    print(f"Yang file: {paths.yang_path}")
    print(f"Yin file: {paths.yin_path}")
    print(f"State file: {args.state_path}")

    if not paths.law_path.exists():
        print("Seeding yin first.")
        ensure_text_file(paths.yin_scratchpad_path, "# Yin Scratchpad\n\n")
        seed_dir = artifact_dir(queue_root, "seed")
        seed_yin_dir = agent_artifact_dir(seed_dir, "yin")
        yin_snapshot = paths.yin_path.read_text(encoding="utf-8")
        seed_prompt = yin_seed_prompt(paths)
        seed_system_prompt = render_system_prompt(
            paths.yin_system_prompt_path,
            "You are yin. Own {yin_file} and nothing else.",
            prompt_context(paths),
        )
        begin_agent_turn_logging(
            agent_dir=seed_yin_dir,
            file_label="yin",
            prompt=seed_prompt,
            system_prompt=seed_system_prompt,
            before_text=yin_snapshot,
            resumed_session_id=None,
        )
        _, yin_text = await run_agent_turn(
            sdk=sdk,
            cwd=ROOT,
            repo_root=ROOT,
            editable_paths=[paths.yin_path.resolve(), paths.yin_scratchpad_path.resolve()],
            prompt=seed_prompt,
            system_prompt=seed_system_prompt,
            max_turns=args.yin_max_turns,
            cli_path=args.cli_path,
            claude_model=args.claude_model,
            claude_home=yin_home,
            session_id=yin_session_name,
        )
        if yin_text:
            print(yin_text)
        yin_after = read_text(paths.yin_path)
        finish_agent_turn_logging(
            agent_dir=seed_yin_dir,
            file_label="yin",
            response=yin_text,
            before_text=yin_snapshot,
            after_text=yin_after,
            session_id=yin_session_name,
            resumed_session_id=None,
        )
        try:
            world = validate_yin(paths)
        except Exception as exc:
            paths.yin_path.write_text(yin_snapshot, encoding="utf-8")
            raise RuntimeError(f"yin seed failed and was reverted: {type(exc).__name__}: {exc}") from exc
        seed_record = append_history(paths, phase="seed", world=world, results={}, passed=False)
        write_json(seed_dir / "world_after.json", world)
        record_seed_idea(
            paths,
            artifact_dir=seed_dir,
            response=yin_text,
            changed=yin_snapshot != yin_after,
            world=world,
        )
        write_iteration_summary(
            seed_dir,
            {
                "phase": "seed",
                "record": seed_record,
                "yin_changed": yin_snapshot != yin_after,
            },
        )

    target_iteration = None if args.iterations < 0 else state.iteration + args.iterations
    while target_iteration is None or state.iteration < target_iteration:
        if args.max_wall_sec > 0 and (time.monotonic() - started_at) >= args.max_wall_sec:
            print(f"Stopping after reaching max wall time of {args.max_wall_sec}s.")
            break

        state.iteration += 1
        print(f"\n== Yin/Yang Iteration {state.iteration} ==")
        ensure_text_file(paths.yang_scratchpad_path, "# Yang Scratchpad\n\n")
        ensure_text_file(paths.yin_scratchpad_path, "# Yin Scratchpad\n\n")

        iter_dir = artifact_dir(queue_root, f"iter-{state.iteration:06d}")
        current_world = run_yin_world(paths)
        write_json(iter_dir / "world_before.json", current_world)
        cycle_state = YangCycleState(paths=paths, max_calls=args.yang_max_cycle_calls, world=current_world, artifact_dir=iter_dir)

        @sdk.tool("run_cycle", "Execute the immutable yin/yang cycle once and return world, results, and pass/fail.", {"note": str})
        async def run_cycle_tool(tool_args: dict[str, Any]) -> dict[str, Any]:
            note = str(tool_args.get("note", "")).strip() or "trial"
            return await cycle_state.run(note)

        server = sdk.create_sdk_mcp_server(name="taiji", tools=[run_cycle_tool])
        yang_dir = agent_artifact_dir(iter_dir, "yang")
        yang_before = read_text(paths.yang_path)
        yang_prompt = yang_turn_prompt(paths, state.iteration)
        yang_system_prompt = render_system_prompt(
            paths.yang_system_prompt_path,
            "You are yang. Own {yang_file} and nothing else.",
            prompt_context(paths, iteration=state.iteration),
        )
        begin_agent_turn_logging(
            agent_dir=yang_dir,
            file_label="yang",
            prompt=yang_prompt,
            system_prompt=yang_system_prompt,
            before_text=yang_before,
            resumed_session_id=state.yang_session_id if args.resume_yang_session else None,
        )
        yang_session_id, yang_text = await run_agent_turn(
            sdk=sdk,
            cwd=ROOT,
            repo_root=ROOT,
            editable_paths=[paths.yang_path.resolve(), paths.yang_scratchpad_path.resolve()],
            prompt=yang_prompt,
            system_prompt=yang_system_prompt,
            max_turns=args.yang_max_turns,
            cli_path=args.cli_path,
            claude_model=args.claude_model,
            claude_home=yang_home,
            resume_session_id=state.yang_session_id if args.resume_yang_session else None,
            session_id=yang_session_name,
            mcp_servers={"taiji": server},
            tools=DEFAULT_AGENT_TOOLS,
            allowed_tools=[
                *DEFAULT_AGENT_TOOLS,
                "mcp__taiji__run_cycle",
            ],
        )
        if yang_text:
            print(yang_text)
        yang_after = read_text(paths.yang_path)
        finish_agent_turn_logging(
            agent_dir=yang_dir,
            file_label="yang",
            response=yang_text,
            before_text=yang_before,
            after_text=yang_after,
            session_id=yang_session_id or yang_session_name,
            resumed_session_id=state.yang_session_id if args.resume_yang_session else None,
        )
        if yang_session_id is not None:
            state.yang_session_id = yang_session_id

        record = cycle_state.last_record
        if record is None:
            print("Yang did not call run_cycle. Continuing.")
            write_iteration_summary(
                iter_dir,
                {
                    "iteration": state.iteration,
                    "status": "yang-no-run",
                    "world_before": current_world,
                    "yang_session_id": state.yang_session_id,
                },
            )
            state.last_phase = "yang-no-run"
            state.last_passed = False
            save_state(args.state_path, state)
            continue

        print(json.dumps(record, indent=2, sort_keys=False))
        write_json(iter_dir / "results.json", record["results"])
        record_yang_idea(
            paths,
            iteration=state.iteration,
            artifact_dir=iter_dir,
            response=yang_text,
            after_text=yang_after,
            record=record,
        )
        if not bool(record["passed"]):
            write_iteration_summary(
                iter_dir,
                {
                    "iteration": state.iteration,
                    "status": "failed",
                    "record": record,
                    "yang_session_id": state.yang_session_id,
                },
            )
            state.last_phase = "round"
            state.last_passed = False
            save_state(args.state_path, state)
            continue

        print("Yang passed. Waking yin to refine the world or the pass condition.")
        previous_world = record.get("world", {})
        yin_dir = agent_artifact_dir(iter_dir, "yin")
        yin_snapshot = paths.yin_path.read_text(encoding="utf-8")
        yin_prompt = yin_turn_prompt(paths, state.iteration)
        yin_system_prompt = render_system_prompt(
            paths.yin_system_prompt_path,
            "You are yin. Own {yin_file} and nothing else.",
            prompt_context(paths, iteration=state.iteration),
        )
        begin_agent_turn_logging(
            agent_dir=yin_dir,
            file_label="yin",
            prompt=yin_prompt,
            system_prompt=yin_system_prompt,
            before_text=yin_snapshot,
            resumed_session_id=None,
        )
        _, yin_text = await run_agent_turn(
            sdk=sdk,
            cwd=ROOT,
            repo_root=ROOT,
            editable_paths=[paths.yin_path.resolve(), paths.yin_scratchpad_path.resolve()],
            prompt=yin_prompt,
            system_prompt=yin_system_prompt,
            max_turns=args.yin_max_turns,
            cli_path=args.cli_path,
            claude_model=args.claude_model,
            claude_home=yin_home,
            session_id=yin_session_name,
        )
        if yin_text:
            print(yin_text)

        try:
            world = validate_yin(paths, record["results"])
        except Exception as exc:
            paths.yin_path.write_text(yin_snapshot, encoding="utf-8")
            world = validate_yin(paths, record["results"])
            print(f"Yin edit failed and was reverted: {type(exc).__name__}: {exc}")

        yin_after = read_text(paths.yin_path)
        finish_agent_turn_logging(
            agent_dir=yin_dir,
            file_label="yin",
            response=yin_text,
            before_text=yin_snapshot,
            after_text=yin_after,
            session_id=yin_session_name,
            resumed_session_id=None,
        )
        yin_changed = paths.yin_path.read_text(encoding="utf-8") != yin_snapshot
        world_changed = world != previous_world
        ratchet_record = append_history(
            paths,
            phase="ratchet",
            world=world,
            results=record["results"],
            passed=True,
            metadata={
                "yin_changed": yin_changed,
                "world_changed": world_changed,
            },
        )
        write_json(iter_dir / "world_after.json", world)
        record_yin_idea(
            paths,
            iteration=state.iteration,
            artifact_dir=iter_dir,
            response=yin_text,
            after_text=yin_after,
            yin_changed=yin_changed,
            world_changed=world_changed,
            results=record["results"],
        )
        write_iteration_summary(
            iter_dir,
            {
                "iteration": state.iteration,
                "status": "passed",
                "trial_record": record,
                "ratchet_record": ratchet_record,
                "yang_session_id": state.yang_session_id,
                "yin_session_id": yin_session_name,
            },
        )
        print(json.dumps(ratchet_record, indent=2, sort_keys=False))

        state.last_phase = "ratchet"
        state.last_passed = True
        save_state(args.state_path, state)

        if args.stop_on_converged and not yin_changed:
            print("Stopping because yin did not change the world or acceptance condition.")
            break


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Taiji yin/yang loop")
    parser.add_argument("--unit-root", type=Path, required=True, help="Unit root for the yin/yang unit")
    parser.add_argument("--iterations", type=int, default=1, help="-1 runs until interrupted; otherwise run this many iterations")
    parser.add_argument("--max-wall-sec", type=int, default=0, help="Stop after this many wall-clock seconds; 0 disables the limit")
    parser.add_argument("--yang-max-turns", type=int, default=8, help="Max Claude turns for each yang edit cycle")
    parser.add_argument("--yang-max-cycle-calls", type=int, default=6, help="Maximum immutable run_cycle calls allowed per yang turn")
    parser.add_argument("--yin-max-turns", type=int, default=6, help="Max Claude turns for each yin edit cycle")
    parser.add_argument("--cli-path", type=str, default=None, help="Optional path to the Claude Code CLI binary")
    parser.add_argument("--claude-model", type=str, default=None, help="Optional Claude model override")
    parser.add_argument("--state-path", type=Path, default=None, help="Loop state path; defaults under unit_root/queue")
    parser.add_argument("--yang-claude-home", type=Path, default=None, help="Claude home for the yang session")
    parser.add_argument("--yin-claude-home", type=Path, default=None, help="Claude home for the yin session")
    parser.add_argument("--resume-yang-session", action="store_true", help="Resume the persistent yang Claude session")
    parser.add_argument("--stop-on-converged", action="store_true", help="Stop when yang passes and yin does not change yin.py")
    return parser


def main() -> None:
    configure_stdio()
    parser = build_parser()
    args = parser.parse_args()
    if args.state_path is None:
        queue_root = dual_loop_paths(args.unit_root).queue_root
        args.state_path = queue_root / "loop_state.json"
    anyio.run(run_loop, args)


if __name__ == "__main__":
    main()
