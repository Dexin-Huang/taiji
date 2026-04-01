"""
Taiji yin/yang loop orchestrator.

This is the main loop that alternates yang (builder) and yin (critic) turns
using the Claude Agent SDK. Yang edits yang.py and tests via the run_cycle
MCP tool. In adaptive mode yin wakes after a pass; in fixed mode yin seeds
once and then stays asleep.
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
    RUN_LIBRARIAN_AGENT_NAME,
    YangCycleState,
    agent_artifact_dir,
    artifact_dir,
    begin_agent_turn_logging,
    ensure_text_file,
    finish_agent_turn_logging,
    load_state,
    make_run_librarian_definition,
    read_text,
    save_state,
    write_iteration_summary,
)
from .cycle import append_history, dual_loop_paths, ensure_run_workspace, evaluate_yang_trial, seed, validate_yin
from .ideas import record_seed_idea, record_yang_idea, record_yin_idea
from .law import evaluate_snapshot, has_materialized_law, load_materialized_snapshot, score_snapshot
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


async def run_yin_turn(args, **kwargs):
    """Dispatch yin turn to Claude or Codex based on --yin-backend."""
    if getattr(args, "yin_backend", None) == "codex":
        from .codex import run_codex_turn
        editable = kwargs["editable_paths"]
        cwd = kwargs.get("cwd", ROOT)
        thread_id, text = await run_codex_turn(
            cwd=cwd,
            editable_paths=editable,
            prompt=kwargs["prompt"],
            system_prompt=kwargs["system_prompt"],
            model=getattr(args, "codex_model", None),
        )
        return thread_id, text
    else:
        sdk = kwargs.pop("sdk")
        return await run_agent_turn(sdk=sdk, **kwargs)


def _snapshot_workspace(workspace_path: Path) -> dict[str, bytes]:
    """Capture all files in workspace/ for potential revert."""
    snapshot = {}
    if workspace_path.exists():
        for f in workspace_path.rglob("*"):
            if f.is_file():
                key = str(f.relative_to(workspace_path))
                snapshot[key] = f.read_bytes()
    return snapshot


def _restore_workspace(workspace_path: Path, snapshot: dict[str, bytes]) -> None:
    """Restore workspace/ to a previous state."""
    if not workspace_path.exists():
        return
    # Remove files not in snapshot
    for f in list(workspace_path.rglob("*")):
        if f.is_file():
            key = str(f.relative_to(workspace_path))
            if key not in snapshot:
                f.unlink()
    # Restore snapshot files
    for key, data in snapshot.items():
        target = workspace_path / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="backslashreplace")


def baseline_record_from_state(state: DualLoopState, *, source_hash: str) -> dict[str, Any] | None:
    if state.yang_kept_source_hash != source_hash:
        return None
    if state.yang_kept_passed is None:
        return None
    return {
        "passed": bool(state.yang_kept_passed),
        "score": state.yang_kept_score or {"order": [], "summary": {}},
        "source_hash": source_hash,
    }


def update_kept_state_from_record(state: DualLoopState, record: dict[str, Any], *, source_hash: str) -> None:
    state.yang_kept_passed = bool(record.get("passed"))
    state.yang_kept_score = dict(record.get("score", {"order": [], "summary": {}}))
    state.yang_kept_source_hash = source_hash


def ensure_yang_baseline(paths: Any, current_law: Any, state: DualLoopState) -> dict[str, Any]:
    baseline = baseline_record_from_state(state, source_hash=current_law.source_hash)
    if baseline is not None:
        return baseline
    baseline = evaluate_yang_trial(
        paths,
        current_law,
        persist_results=False,
        persist_history=False,
        phase="baseline",
    )
    update_kept_state_from_record(state, baseline, source_hash=current_law.source_hash)
    return baseline


def restore_results_file(paths: Any, previous_text: str | None) -> None:
    if previous_text is None:
        paths.results_path.unlink(missing_ok=True)
        return
    paths.results_path.parent.mkdir(parents=True, exist_ok=True)
    paths.results_path.write_text(previous_text, encoding="utf-8")


def seed_retry_prompt(base_prompt: str, *, attempt: int, error: Exception | None) -> str:
    if error is None:
        return base_prompt
    error_text = f"{type(error).__name__}: {error}"
    return (
        f"{base_prompt}\n\n"
        f"Previous seed validation attempt {attempt - 1} failed and was reverted.\n"
        f"Validation error:\n{error_text}\n\n"
        "Fix yin.py so it validates mechanically.\n"
        "If score(results) is defined, it must accept empty, partial, or failed results "
        "and always return finite numeric values."
    )


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

async def run_loop(args: argparse.Namespace) -> None:
    paths = dual_loop_paths(args.unit_root, run_id=args.run_id, create_run=True)
    bootstrap_unit(paths.unit_root, include_readme=False, require_prompt=True)
    paths = dual_loop_paths(paths.unit_root, run_id=args.run_id, create_run=True)
    ensure_run_workspace(paths)
    adaptive_mode = args.mode == "adaptive"
    queue_root = paths.queue_root
    queue_root.mkdir(parents=True, exist_ok=True)
    state = load_state(args.state_path)
    sdk = load_claude_agent_sdk()

    slug = session_slug(paths.run_root, ROOT)
    yang_session_name = f"taiji-yang-{slug}"
    yin_session_name = f"taiji-yin-{slug}"
    yang_home = args.yang_claude_home or (queue_root / "yang-claude-home")
    yin_home = args.yin_claude_home or (queue_root / "yin-claude-home")
    started_at = time.monotonic()

    sdk_source = claude_sdk_reference_root() if claude_sdk_reference_root().exists() else "installed package"
    print(f"SDK source: {sdk_source}")
    print(f"Unit root: {paths.unit_root}")
    print(f"Run id: {paths.run_id}")
    print(f"Mode: {args.mode}")
    print(f"Yang seed: {paths.yang_seed_path}")
    print(f"Yin seed: {paths.yin_seed_path}")
    print(f"Yang file: {paths.yang_path}")
    print(f"Yin file: {paths.yin_path}")
    print(f"State file: {args.state_path}")

    # -- Seed phase ----------------------------------------------------------
    if not has_materialized_law(paths):
        print("Seeding yin first.")
        ensure_text_file(paths.yin_scratchpad_path, "# Yin Scratchpad\n\n")
        seed_dir = artifact_dir(queue_root, "seed")
        seed_attempt = 0
        seed_resume_session_id: str | None = None
        seed_validation_error: Exception | None = None
        while not has_materialized_law(paths):
            seed_attempt += 1
            attempt_dir = agent_artifact_dir(
                artifact_dir(queue_root, f"seed-attempt-{seed_attempt:04d}"),
                "yin",
            )
            yin_snapshot = paths.yin_path.read_text(encoding="utf-8")
            ctx = prompt_context(paths, ROOT)
            seed_prompt = seed_retry_prompt(
                yin_seed_prompt(paths, ROOT),
                attempt=seed_attempt,
                error=seed_validation_error,
            )
            seed_sys = render_system_prompt(
                paths.yin_system_prompt_path,
                "You are yin. Own {yin_file} and nothing else.",
                ctx,
            )
            resumed_seed_session_id = seed_resume_session_id
            begin_agent_turn_logging(
                agent_dir=attempt_dir,
                file_label="yin",
                prompt=seed_prompt,
                system_prompt=seed_sys,
                before_text=yin_snapshot,
                resumed_session_id=resumed_seed_session_id,
            )
            seed_resume_session_id, yin_text = await run_yin_turn(
                args,
                sdk=sdk, cwd=ROOT, repo_root=ROOT,
                editable_paths=[paths.yin_path.resolve(), paths.yin_scratchpad_path.resolve(), paths.yin_notebook_path.resolve()],
                prompt=seed_prompt, system_prompt=seed_sys,
                max_turns=args.yin_max_turns, cli_path=args.cli_path,
                claude_model=args.claude_model, claude_home=yin_home,
                resume_session_id=resumed_seed_session_id,
                session_id=yin_session_name,
            )
            if yin_text:
                print(yin_text)
            yin_after = read_text(paths.yin_path)
            finish_agent_turn_logging(
                agent_dir=attempt_dir,
                file_label="yin",
                response=yin_text,
                before_text=yin_snapshot,
                after_text=yin_after,
                session_id=seed_resume_session_id or yin_session_name,
                resumed_session_id=resumed_seed_session_id,
            )
            try:
                seed_record = seed(paths)
            except Exception as exc:
                seed_validation_error = exc
                paths.yin_path.write_text(yin_snapshot, encoding="utf-8")
                (attempt_dir / "validation_error.txt").write_text(
                    f"{type(exc).__name__}: {exc}\n",
                    encoding="utf-8",
                )
                write_iteration_summary(attempt_dir.parent, {
                    "phase": "seed-attempt",
                    "attempt": seed_attempt,
                    "status": "validation_failed",
                    "mode": args.mode,
                    "error": f"{type(exc).__name__}: {exc}",
                    "yin_changed": yin_snapshot != yin_after,
                })
                print(f"Seed validation failed on attempt {seed_attempt}: {type(exc).__name__}: {exc}")
                print("Reverted yin.py and retrying seed.")
                continue

            world = seed_record["world"]
            write_json(seed_dir / "world_after.json", world)
            record_seed_idea(
                paths,
                ROOT,
                artifact_dir=seed_dir,
                response=yin_text,
                changed=yin_snapshot != yin_after,
                world=world,
            )
            write_iteration_summary(seed_dir, {
                "phase": "seed",
                "mode": args.mode,
                "record": seed_record,
                "yin_changed": yin_snapshot != yin_after,
                "attempts": seed_attempt,
            })
            break

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
        current_law = load_materialized_snapshot(paths)
        current_world = current_law.world
        write_json(iter_dir / "world_before.json", current_world)
        baseline = ensure_yang_baseline(paths, current_law, state)
        cycle_state = YangCycleState(
            paths=paths,
            max_calls=args.yang_max_cycle_calls,
            law=current_law,
            artifact_dir=iter_dir,
            baseline_record=baseline,
        )

        # -- Yang turn -------------------------------------------------------
        @sdk.tool("run_cycle", "Execute the immutable yin/yang cycle once and return world, results, and pass/fail.", {"note": str})
        async def run_cycle_tool(tool_args: dict[str, Any]) -> dict[str, Any]:
            note = str(tool_args.get("note", "")).strip() or "trial"
            return await cycle_state.run(note)

        server = sdk.create_sdk_mcp_server(name="taiji", tools=[run_cycle_tool])
        yang_dir = agent_artifact_dir(iter_dir, "yang")
        yang_before = read_text(paths.yang_path)
        # Snapshot workspace for potential revert
        workspace_snapshot = _snapshot_workspace(paths.workspace_path)
        results_before = read_text(paths.results_path) if paths.results_path.exists() else None
        ctx = prompt_context(paths, ROOT, iteration=state.iteration)
        yang_prompt = yang_turn_prompt(paths, ROOT, state.iteration)
        yang_sys = render_system_prompt(paths.yang_system_prompt_path, "You are yang. Own {yang_file} and nothing else.", ctx)
        yang_agents = {
            RUN_LIBRARIAN_AGENT_NAME: make_run_librarian_definition(sdk, paths, ROOT),
        }
        resumed_yang_session_id = state.yang_session_id if args.resume_yang_session else None
        begin_agent_turn_logging(
            agent_dir=yang_dir, file_label="yang",
            prompt=yang_prompt, system_prompt=yang_sys,
            before_text=yang_before,
            resumed_session_id=resumed_yang_session_id,
        )
        yang_session_id, yang_text = await run_agent_turn(
            sdk=sdk, cwd=ROOT, repo_root=ROOT,
            editable_paths=[paths.yang_path.resolve(), paths.yang_scratchpad_path.resolve(), paths.yang_notebook_path.resolve()],
            editable_dirs=[paths.workspace_path.resolve()],
            prompt=yang_prompt, system_prompt=yang_sys,
            max_turns=args.yang_max_turns, cli_path=args.cli_path,
            claude_model=args.claude_model, claude_home=yang_home,
            resume_session_id=resumed_yang_session_id,
            session_id=yang_session_name,
            mcp_servers={"taiji": server},
            tools=DEFAULT_AGENT_TOOLS,
            allowed_tools=[*DEFAULT_AGENT_TOOLS, "mcp__taiji__run_cycle"],
            agents=yang_agents,
        )
        if yang_text:
            print(yang_text)
        yang_turn_end = read_text(paths.yang_path)
        if yang_session_id is not None:
            state.yang_session_id = yang_session_id

        keep_decision: dict[str, Any]
        active_record = baseline
        kept_new_candidate = cycle_state.best_record is not None
        attempt_record = cycle_state.best_record if cycle_state.best_record is not None else cycle_state.last_record
        attempted_yang_text = cycle_state.best_yang_text if cycle_state.best_record is not None else yang_turn_end
        if kept_new_candidate:
            assert cycle_state.best_record is not None
            assert cycle_state.best_yang_text is not None
            paths.yang_path.write_text(cycle_state.best_yang_text, encoding="utf-8")
            write_json(paths.results_path, cycle_state.best_record["results"])
            active_record = cycle_state.best_record
            update_kept_state_from_record(state, active_record, source_hash=current_law.source_hash)
            keep_decision = {
                "action": "keep",
                "reason": "passed" if bool(active_record["passed"]) else "score-improved",
                "baseline": baseline,
                "active": active_record,
            }
        else:
            paths.yang_path.write_text(yang_before, encoding="utf-8")
            restore_results_file(paths, results_before)
            _restore_workspace(paths.workspace_path, workspace_snapshot)
            keep_decision = {
                "action": "discard",
                "reason": "no-run" if cycle_state.last_record is None else "no-improvement",
                "baseline": baseline,
                "active": baseline,
            }

        yang_after = read_text(paths.yang_path)
        finish_agent_turn_logging(
            agent_dir=yang_dir, file_label="yang",
            response=yang_text, before_text=yang_before, after_text=yang_after,
            session_id=yang_session_id or yang_session_name,
            resumed_session_id=resumed_yang_session_id,
        )

        if attempt_record is not None:
            print(json.dumps(attempt_record, indent=2, sort_keys=False))
            write_json(iter_dir / "results.json", attempt_record["results"])
            record_yang_idea(
                paths,
                ROOT,
                iteration=state.iteration,
                artifact_dir=iter_dir,
                response=yang_text,
                after_text=attempted_yang_text,
                record=attempt_record,
                selection=keep_decision,
            )

        if cycle_state.last_record is None:
            print("Yang did not call run_cycle. Continuing.")
            write_iteration_summary(iter_dir, {
                "iteration": state.iteration,
                "status": "yang-no-run",
                "mode": args.mode,
                "world_before": current_world,
                "law_source_hash": current_law.source_hash,
                "yang_session_id": state.yang_session_id,
                "attempt_record": None,
                "kept_record": active_record,
                "keep_decision": keep_decision,
            })
            state.last_phase = "yang-no-run"
            state.last_passed = bool(active_record["passed"])
            save_state(args.state_path, state)
            continue

        if not kept_new_candidate:
            summary_status = "already-passing" if bool(active_record["passed"]) else "failed"
            write_iteration_summary(iter_dir, {
                "iteration": state.iteration,
                "status": summary_status,
                "mode": args.mode,
                "attempt_record": attempt_record,
                "kept_record": active_record,
                "keep_decision": keep_decision,
                "law_source_hash": current_law.source_hash,
                "yang_session_id": state.yang_session_id,
            })
            state.last_phase = "round"
            state.last_passed = bool(active_record["passed"])
            save_state(args.state_path, state)
            if bool(active_record["passed"]) and not adaptive_mode:
                print("Active yang already passes current law. Fixed mode stops here.")
                break
            continue

        record = active_record

        if not bool(record["passed"]):
            write_iteration_summary(iter_dir, {
                "iteration": state.iteration, "status": "failed",
                "mode": args.mode,
                "attempt_record": attempt_record,
                "kept_record": record,
                "keep_decision": keep_decision,
                "law_source_hash": current_law.source_hash,
                "yang_session_id": state.yang_session_id,
            })
            state.last_phase = "round"
            state.last_passed = False
            save_state(args.state_path, state)
            continue

        if not adaptive_mode:
            print("Yang passed. Fixed mode keeps yin asleep and preserves the active law snapshot.")
            write_iteration_summary(iter_dir, {
                "iteration": state.iteration,
                "status": "passed",
                "mode": args.mode,
                "trial_record": record,
                "attempt_record": attempt_record,
                "kept_record": record,
                "keep_decision": keep_decision,
                "law_source_hash": current_law.source_hash,
                "yang_session_id": state.yang_session_id,
            })
            state.last_phase = "fixed"
            state.last_passed = True
            save_state(args.state_path, state)
            break

        # -- Yin turn (adaptive mode only after yang passes) -------------------
        print("Yang passed. Adaptive mode wakes yin to refine the world or the pass condition.")
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
        _, yin_text = await run_yin_turn(
            args,
            sdk=sdk, cwd=ROOT, repo_root=ROOT,
            editable_paths=[paths.yin_path.resolve(), paths.yin_scratchpad_path.resolve(), paths.yin_notebook_path.resolve()],
            prompt=yin_prompt, system_prompt=yin_sys,
            max_turns=args.yin_max_turns, cli_path=args.cli_path,
            claude_model=args.claude_model, claude_home=yin_home,
            session_id=yin_session_name,
        )
        if yin_text:
            print(yin_text)

        adaptive_status = "applied"
        try:
            validation = validate_yin(paths, record["results"])
            active_law = validation.snapshot
            world = active_law.world
            probe_passed = validation.probe_passed
            probe_score = validation.probe_score
        except Exception as exc:
            paths.yin_path.write_text(yin_snapshot, encoding="utf-8")
            active_law = load_materialized_snapshot(paths)
            world = active_law.world
            probe_passed = evaluate_snapshot(paths, active_law, record["results"])
            probe_score = score_snapshot(paths, active_law, record["results"])
            adaptive_status = "reverted"
            print(f"Yin edit failed and was reverted: {type(exc).__name__}: {exc}")

        yin_after = read_text(paths.yin_path)
        finish_agent_turn_logging(
            agent_dir=yin_dir, file_label="yin",
            response=yin_text, before_text=yin_snapshot, after_text=yin_after,
            session_id=yin_session_name, resumed_session_id=None,
        )
        yin_changed = yin_after != yin_snapshot
        world_changed = world != previous_world
        if adaptive_status != "reverted" and not yin_changed and not world_changed:
            adaptive_status = "no_change"
        adaptive_record = append_history(
            paths,
            phase="adaptive",
            world=world,
            results=record["results"],
            passed=probe_passed,
            score=probe_score.to_json(),
            metadata={
                "status": adaptive_status,
                "yin_changed": yin_changed,
                "world_changed": world_changed,
                "prior_results_pass_under_current_law": probe_passed,
                "source_hash": active_law.source_hash,
            },
        )
        write_json(iter_dir / "world_after.json", world)
        record_yin_idea(
            paths, ROOT, iteration=state.iteration, artifact_dir=iter_dir,
            response=yin_text, after_text=yin_after,
            yin_changed=yin_changed, world_changed=world_changed, results=record["results"], status=adaptive_status,
        )
        write_iteration_summary(iter_dir, {
            "iteration": state.iteration, "status": adaptive_status,
            "mode": args.mode,
            "trial_record": record,
            "attempt_record": attempt_record,
            "kept_record": record,
            "keep_decision": keep_decision,
            "adaptive_record": adaptive_record,
            "law_source_hash": active_law.source_hash,
            "yang_session_id": state.yang_session_id, "yin_session_id": yin_session_name,
        })
        print(json.dumps(adaptive_record, indent=2, sort_keys=False))

        state.last_phase = "adaptive"
        state.last_passed = probe_passed
        update_kept_state_from_record(
            state,
            {"passed": probe_passed, "score": probe_score.to_json()},
            source_hash=active_law.source_hash,
        )
        save_state(args.state_path, state)

        if args.stop_on_converged and adaptive_status == "no_change":
            print("Stopping because yin did not change the world or acceptance condition.")
            break


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Taiji yin/yang loop")
    parser.add_argument("--unit-root", type=Path, required=True)
    parser.add_argument("--run-id", type=str, default=None, help="Resume or target a specific run id")
    parser.add_argument("--new", action="store_true", help="Start a fresh run in a new run folder")
    parser.add_argument(
        "--mode",
        choices=("fixed", "adaptive"),
        default="adaptive",
        help="fixed = seed yin once and keep the world/law fixed; adaptive = let yin refine after passing rounds",
    )
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
    parser.add_argument("--resume-yang-session", action="store_true", default=True,
                        help="Resume yang's Claude session across iterations (default: true)")
    parser.add_argument("--no-resume-yang-session", action="store_false", dest="resume_yang_session")
    parser.add_argument(
        "--yin-backend",
        choices=("claude", "codex"),
        default="claude",
        help="Which model backend to use for yin turns (default: claude)",
    )
    parser.add_argument("--codex-model", type=str, default=None, help="Model for codex backend (default: from ~/.codex/config.toml)")
    parser.add_argument(
        "--stop-on-converged",
        action="store_true",
        help="adaptive mode only: stop after a passing iteration where yin makes no change",
    )
    return parser


def main() -> None:
    configure_stdio()
    parser = build_parser()
    args = parser.parse_args()
    paths = dual_loop_paths(args.unit_root, run_id=args.run_id, create_run=True, new_run=args.new)
    args.run_id = paths.run_id
    if args.state_path is None:
        args.state_path = paths.queue_root / "loop_state.json"
    anyio.run(run_loop, args)


if __name__ == "__main__":
    main()
