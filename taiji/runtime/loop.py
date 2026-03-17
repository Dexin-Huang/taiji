"""
Taiji yin/yang loop orchestrator.

This is the main loop that alternates yang (builder) and yin (critic) turns
using the Claude Agent SDK. Yang edits yang.py and tests via the run_cycle
MCP tool. When yang passes, yin wakes to raise the bar.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import anyio

from .bootstrap import bootstrap_unit
from .agents import (
    DEFAULT_AGENT_TOOLS,
    DualLoopState,
    YangCycleState,
    agent_artifact_dir,
    artifact_dir,
    begin_agent_turn_logging,
    ensure_text_file,
    finish_agent_turn_logging,
    load_state,
    read_text,
    save_state,
    write_iteration_summary,
    write_text,
)
from .cycle import append_history, dual_loop_paths, run_yin_world, validate_yin
from .ideas import record_seed_idea, record_yang_idea, record_yin_idea
from .prompts import (
    prompt_context,
    render_system_prompt,
    session_slug,
    yang_turn_prompt,
    yin_seed_prompt,
    yin_turn_prompt,
)
from .schema import ROOT, write_json
from .sdk_loader import claude_sdk_reference_root, load_claude_agent_sdk
from .agents import run_agent_turn


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="backslashreplace")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

async def run_loop(args: argparse.Namespace) -> None:
    paths = dual_loop_paths(args.unit_root)
    bootstrap_unit(paths.unit_root, include_readme=False, require_prompt=True)
    queue_root = paths.queue_root
    queue_root.mkdir(parents=True, exist_ok=True)
    state = load_state(args.state_path)
    sdk = load_claude_agent_sdk()

    slug = session_slug(paths.unit_root, ROOT)
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

    # -- Seed phase ----------------------------------------------------------
    if not paths.law_path.exists():
        print("Seeding yin first.")
        ensure_text_file(paths.yin_scratchpad_path, "# Yin Scratchpad\n\n")
        seed_dir = artifact_dir(queue_root, "seed")
        seed_yin_dir = agent_artifact_dir(seed_dir, "yin")
        yin_snapshot = paths.yin_path.read_text(encoding="utf-8")
        ctx = prompt_context(paths, ROOT)
        seed_prompt = yin_seed_prompt(paths, ROOT)
        seed_sys = render_system_prompt(
            paths.yin_system_prompt_path,
            "You are yin. Own {yin_file} and nothing else.",
            ctx,
        )
        begin_agent_turn_logging(
            agent_dir=seed_yin_dir, file_label="yin",
            prompt=seed_prompt, system_prompt=seed_sys,
            before_text=yin_snapshot, resumed_session_id=None,
        )
        _, yin_text = await run_agent_turn(
            sdk=sdk, cwd=ROOT, repo_root=ROOT,
            editable_paths=[paths.yin_path.resolve(), paths.yin_scratchpad_path.resolve()],
            prompt=seed_prompt, system_prompt=seed_sys,
            max_turns=args.yin_max_turns, cli_path=args.cli_path,
            claude_model=args.claude_model, claude_home=yin_home,
            session_id=yin_session_name,
        )
        if yin_text:
            print(yin_text)
        yin_after = read_text(paths.yin_path)
        finish_agent_turn_logging(
            agent_dir=seed_yin_dir, file_label="yin",
            response=yin_text, before_text=yin_snapshot, after_text=yin_after,
            session_id=yin_session_name, resumed_session_id=None,
        )
        try:
            world = validate_yin(paths)
        except Exception as exc:
            paths.yin_path.write_text(yin_snapshot, encoding="utf-8")
            raise RuntimeError(f"yin seed failed and was reverted: {type(exc).__name__}: {exc}") from exc
        seed_record = append_history(paths, phase="seed", world=world, results={}, passed=False)
        write_json(seed_dir / "world_after.json", world)
        record_seed_idea(paths, ROOT, artifact_dir=seed_dir, response=yin_text, changed=yin_snapshot != yin_after, world=world)
        write_iteration_summary(seed_dir, {"phase": "seed", "record": seed_record, "yin_changed": yin_snapshot != yin_after})

    # -- Main loop ------------------------------------------------------------
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

        # -- Yang turn -------------------------------------------------------
        @sdk.tool("run_cycle", "Execute the immutable yin/yang cycle once and return world, results, and pass/fail.", {"note": str})
        async def run_cycle_tool(tool_args: dict[str, Any]) -> dict[str, Any]:
            note = str(tool_args.get("note", "")).strip() or "trial"
            return await cycle_state.run(note)

        server = sdk.create_sdk_mcp_server(name="taiji", tools=[run_cycle_tool])
        yang_dir = agent_artifact_dir(iter_dir, "yang")
        yang_before = read_text(paths.yang_path)
        ctx = prompt_context(paths, ROOT, iteration=state.iteration)
        yang_prompt = yang_turn_prompt(paths, ROOT, state.iteration)
        yang_sys = render_system_prompt(paths.yang_system_prompt_path, "You are yang. Own {yang_file} and nothing else.", ctx)
        begin_agent_turn_logging(
            agent_dir=yang_dir, file_label="yang",
            prompt=yang_prompt, system_prompt=yang_sys,
            before_text=yang_before,
            resumed_session_id=state.yang_session_id if args.resume_yang_session else None,
        )
        yang_session_id, yang_text = await run_agent_turn(
            sdk=sdk, cwd=ROOT, repo_root=ROOT,
            editable_paths=[paths.yang_path.resolve(), paths.yang_scratchpad_path.resolve()],
            prompt=yang_prompt, system_prompt=yang_sys,
            max_turns=args.yang_max_turns, cli_path=args.cli_path,
            claude_model=args.claude_model, claude_home=yang_home,
            resume_session_id=state.yang_session_id if args.resume_yang_session else None,
            session_id=yang_session_name,
            mcp_servers={"taiji": server},
            tools=DEFAULT_AGENT_TOOLS,
            allowed_tools=[*DEFAULT_AGENT_TOOLS, "mcp__taiji__run_cycle"],
        )
        if yang_text:
            print(yang_text)
        yang_after = read_text(paths.yang_path)
        finish_agent_turn_logging(
            agent_dir=yang_dir, file_label="yang",
            response=yang_text, before_text=yang_before, after_text=yang_after,
            session_id=yang_session_id or yang_session_name,
            resumed_session_id=state.yang_session_id if args.resume_yang_session else None,
        )
        if yang_session_id is not None:
            state.yang_session_id = yang_session_id

        record = cycle_state.last_record
        if record is None:
            print("Yang did not call run_cycle. Continuing.")
            write_iteration_summary(iter_dir, {
                "iteration": state.iteration, "status": "yang-no-run",
                "world_before": current_world, "yang_session_id": state.yang_session_id,
            })
            state.last_phase = "yang-no-run"
            state.last_passed = False
            save_state(args.state_path, state)
            continue

        print(json.dumps(record, indent=2, sort_keys=False))
        write_json(iter_dir / "results.json", record["results"])
        record_yang_idea(paths, ROOT, iteration=state.iteration, artifact_dir=iter_dir, response=yang_text, after_text=yang_after, record=record)

        if not bool(record["passed"]):
            write_iteration_summary(iter_dir, {
                "iteration": state.iteration, "status": "failed",
                "record": record, "yang_session_id": state.yang_session_id,
            })
            state.last_phase = "round"
            state.last_passed = False
            save_state(args.state_path, state)
            continue

        # -- Yin turn (only after yang passes) --------------------------------
        print("Yang passed. Waking yin to refine the world or the pass condition.")
        previous_world = record.get("world", {})
        yin_dir = agent_artifact_dir(iter_dir, "yin")
        yin_snapshot = paths.yin_path.read_text(encoding="utf-8")
        ctx = prompt_context(paths, ROOT, iteration=state.iteration)
        yin_prompt = yin_turn_prompt(paths, ROOT, state.iteration)
        yin_sys = render_system_prompt(paths.yin_system_prompt_path, "You are yin. Own {yin_file} and nothing else.", ctx)
        begin_agent_turn_logging(
            agent_dir=yin_dir, file_label="yin",
            prompt=yin_prompt, system_prompt=yin_sys,
            before_text=yin_snapshot, resumed_session_id=None,
        )
        _, yin_text = await run_agent_turn(
            sdk=sdk, cwd=ROOT, repo_root=ROOT,
            editable_paths=[paths.yin_path.resolve(), paths.yin_scratchpad_path.resolve()],
            prompt=yin_prompt, system_prompt=yin_sys,
            max_turns=args.yin_max_turns, cli_path=args.cli_path,
            claude_model=args.claude_model, claude_home=yin_home,
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
            agent_dir=yin_dir, file_label="yin",
            response=yin_text, before_text=yin_snapshot, after_text=yin_after,
            session_id=yin_session_name, resumed_session_id=None,
        )
        yin_changed = yin_after != yin_snapshot
        world_changed = world != previous_world
        ratchet_record = append_history(
            paths, phase="ratchet", world=world, results=record["results"], passed=True,
            metadata={"yin_changed": yin_changed, "world_changed": world_changed},
        )
        write_json(iter_dir / "world_after.json", world)
        record_yin_idea(
            paths, ROOT, iteration=state.iteration, artifact_dir=iter_dir,
            response=yin_text, after_text=yin_after,
            yin_changed=yin_changed, world_changed=world_changed, results=record["results"],
        )
        write_iteration_summary(iter_dir, {
            "iteration": state.iteration, "status": "passed",
            "trial_record": record, "ratchet_record": ratchet_record,
            "yang_session_id": state.yang_session_id, "yin_session_id": yin_session_name,
        })
        print(json.dumps(ratchet_record, indent=2, sort_keys=False))

        state.last_phase = "ratchet"
        state.last_passed = True
        save_state(args.state_path, state)

        if args.stop_on_converged and not yin_changed:
            print("Stopping because yin did not change the world or acceptance condition.")
            break


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Taiji yin/yang loop")
    parser.add_argument("--unit-root", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=1, help="-1 = run until interrupted")
    parser.add_argument("--max-wall-sec", type=int, default=0, help="0 = no limit")
    parser.add_argument("--yang-max-turns", type=int, default=8)
    parser.add_argument("--yang-max-cycle-calls", type=int, default=6)
    parser.add_argument("--yin-max-turns", type=int, default=6)
    parser.add_argument("--cli-path", type=str, default=None)
    parser.add_argument("--claude-model", type=str, default=None)
    parser.add_argument("--state-path", type=Path, default=None)
    parser.add_argument("--yang-claude-home", type=Path, default=None)
    parser.add_argument("--yin-claude-home", type=Path, default=None)
    parser.add_argument("--resume-yang-session", action="store_true")
    parser.add_argument("--stop-on-converged", action="store_true")
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
