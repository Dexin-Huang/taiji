"""Claude Agent SDK turn execution for the taiji loop."""

from __future__ import annotations

import difflib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .cycle import evaluate_yang_trial, trial_beats
from .schema import write_json
from .prompts import read_text, relative_artifact_path, run_librarian_prompt


DEFAULT_AGENT_TOOLS = [
    "Read",
    "Glob",
    "Grep",
    "Write",
    "Edit",
    "MultiEdit",
    "WebFetch",
    "WebSearch",
    "Task",
    "Bash",
]

RUN_LIBRARIAN_AGENT_NAME = "run_librarian"
RUN_LIBRARIAN_AGENT_TOOLS = ["Read", "Glob", "Grep"]


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

@dataclass
class DualLoopState:
    iteration: int = 0
    yang_session_id: str | None = None
    last_phase: str | None = None
    last_passed: bool | None = None
    yang_kept_passed: bool | None = None
    yang_kept_score: dict[str, Any] | None = None
    yang_kept_source_hash: str | None = None


@dataclass
class YangCycleState:
    paths: Any
    max_calls: int
    law: Any
    artifact_dir: Path | None = None
    baseline_record: dict[str, Any] | None = None
    calls: int = 0
    last_record: dict[str, Any] | None = None
    best_record: dict[str, Any] | None = None
    best_yang_text: str | None = None

    async def run(self, note: str) -> dict[str, Any]:
        if self.calls >= self.max_calls:
            return {
                "content": [{"type": "text", "text": "run_cycle call limit reached for this turn. Summarize and stop."}]
            }
        self.calls += 1
        record = evaluate_yang_trial(
            self.paths,
            self.law,
            persist_results=True,
            persist_history=True,
            phase="trial",
        )
        self.last_record = record
        current_yang = read_text(self.paths.yang_path)
        current_best = self.baseline_record if self.best_record is None else self.best_record
        if trial_beats(record, current_best):
            self.best_record = record
            self.best_yang_text = current_yang
        payload = {
            "note": note,
            "passed": record["passed"],
            "world": self.law.world,
            "results": record["results"],
            "score": record["score"],
            "source_hash": self.law.source_hash,
        }
        if self.artifact_dir is not None:
            cycle_dir = self.artifact_dir / "run_cycle"
            cycle_dir.mkdir(parents=True, exist_ok=True)
            write_json(cycle_dir / f"call-{self.calls:02d}.json", {
                "call": self.calls, "note": note, "record": record, "payload": payload,
            })
        return {"content": [{"type": "text", "text": json.dumps(payload, indent=2, sort_keys=False)}]}


def run_librarian_config(paths: Any, root: Path) -> dict[str, Any]:
    run_root = relative_artifact_path(paths.run_root, root)
    return {
        "name": RUN_LIBRARIAN_AGENT_NAME,
        "description": (
            f"Read-only librarian for artifacts under {run_root}. "
            "Use it for targeted retrieval about prior attempts, diffs, metrics, scratchpads, ideas, or frontier files."
        ),
        "prompt": run_librarian_prompt(paths, root),
        "tools": list(RUN_LIBRARIAN_AGENT_TOOLS),
        "model": "inherit",
    }


def make_run_librarian_definition(sdk: Any, paths: Any, root: Path) -> Any:
    config = run_librarian_config(paths, root)
    return sdk.AgentDefinition(
        description=config["description"],
        prompt=config["prompt"],
        tools=config["tools"],
        model=config["model"],
    )


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

def load_state(path: Path) -> DualLoopState:
    if not path.exists():
        return DualLoopState()
    return DualLoopState(**json.loads(path.read_text(encoding="utf-8")))


def save_state(path: Path, state: DualLoopState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, asdict(state))


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------

def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def ensure_text_file(path: Path, initial_text: str = "") -> None:
    if not path.exists():
        write_text(path, initial_text)


def write_diff(path: Path, before: str, after: str, *, fromfile: str, tofile: str) -> None:
    diff = "".join(difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile=fromfile, tofile=tofile,
    ))
    write_text(path, diff or "No changes.\n")


# ---------------------------------------------------------------------------
# Artifact logging
# ---------------------------------------------------------------------------

def artifact_dir(queue_root: Path, label: str) -> Path:
    directory = queue_root / "iterations" / label
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def agent_artifact_dir(iter_dir: Path, agent: str) -> Path:
    directory = iter_dir / agent
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def begin_agent_turn_logging(
    *, agent_dir: Path, file_label: str, prompt: str, system_prompt: str,
    before_text: str, resumed_session_id: str | None,
) -> None:
    write_text(agent_dir / "prompt.txt", prompt)
    write_text(agent_dir / "system_prompt.txt", system_prompt)
    write_text(agent_dir / f"{file_label}.before.py", before_text)
    write_text(agent_dir / "response.md", "")
    write_json(agent_dir / "turn.json", {"resumed_session_id": resumed_session_id, "status": "running"})


def finish_agent_turn_logging(
    *, agent_dir: Path, file_label: str, response: str, before_text: str,
    after_text: str, session_id: str | None, resumed_session_id: str | None,
    conversation_log: list[dict[str, Any]] | None = None,
) -> None:
    write_text(agent_dir / "response.md", response or "")
    write_text(agent_dir / f"{file_label}.after.py", after_text)
    write_diff(
        agent_dir / f"{file_label}.diff.patch", before_text, after_text,
        fromfile=f"{file_label}.before.py", tofile=f"{file_label}.after.py",
    )
    write_json(agent_dir / "turn.json", {
        "session_id": session_id, "resumed_session_id": resumed_session_id,
        "changed": before_text != after_text, "status": "completed",
    })
    if conversation_log:
        write_json(agent_dir / "conversation.json", conversation_log)


def write_iteration_summary(iter_dir: Path, payload: dict[str, Any]) -> None:
    write_json(iter_dir / "summary.json", payload)


# ---------------------------------------------------------------------------
# Edit restriction hook
# ---------------------------------------------------------------------------

def resolve_edit_path(raw_path: str, cwd: Path, repo_root: Path) -> Path:
    normalized = raw_path.replace("\\", "/")
    if normalized == "/workspace" or normalized.startswith("/workspace/"):
        suffix = normalized.removeprefix("/workspace").lstrip("/")
        return (repo_root / suffix).resolve()
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = cwd / candidate
    return candidate.resolve()


def make_edit_hook(editable_set: set[Path], cwd: Path, repo_root: Path, editable_dirs: set[Path] | None = None):
    """Return an async hook that restricts Write/Edit to *editable_set* or under *editable_dirs*."""
    _editable_dirs = editable_dirs or set()

    async def restrict_edits(input_data: dict[str, Any], tool_use_id: str | None, context: dict[str, Any]) -> dict[str, Any]:
        tool_name = input_data.get("tool_name")
        if tool_name not in {"Write", "Edit", "MultiEdit"}:
            return {}
        raw_path = input_data.get("tool_input", {}).get("file_path")
        if not raw_path:
            return _deny("Missing file_path on edit request.")
        target = resolve_edit_path(str(raw_path), cwd, repo_root)
        # Check exact file match
        if target in editable_set:
            return _allow("Edit stays inside the owned file.")
        # Check directory prefix match
        for d in _editable_dirs:
            try:
                target.relative_to(d)
                return _allow(f"Edit inside owned directory {d.name}/.")
            except ValueError:
                continue
        owned = ", ".join(sorted(p.name for p in editable_set))
        dirs = ", ".join(sorted(d.name + "/" for d in _editable_dirs))
        desc = f"{owned}, {dirs}" if dirs else owned
        return _deny(f"Only {desc} may be edited in this turn.")

    return restrict_edits


def _deny(reason: str) -> dict[str, Any]:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}}


def _allow(reason: str) -> dict[str, Any]:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow", "permissionDecisionReason": reason}}


# ---------------------------------------------------------------------------
# Agent turn runner
# ---------------------------------------------------------------------------

async def run_agent_turn(
    *,
    sdk: Any,
    cwd: Path,
    repo_root: Path,
    editable_paths: list[Path],
    editable_dirs: list[Path] | None = None,
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
    agents: dict[str, Any] | None = None,
) -> tuple[str | None, str]:
    claude_home.mkdir(parents=True, exist_ok=True)
    editable_set = {p.resolve() for p in editable_paths}
    editable_dir_set = {p.resolve() for p in (editable_dirs or [])}
    restrict_edits = make_edit_hook(editable_set, cwd, repo_root, editable_dir_set)

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
        agents=agents,
        env={
            "HOME": str(claude_home),
            "XDG_CONFIG_HOME": str(claude_home / "config"),
            "XDG_CACHE_HOME": str(claude_home / "cache"),
        },
    )

    assistant_lines: list[str] = []
    conversation_log: list[dict[str, Any]] = []
    final_session_id: str | None = None

    import time as _time
    max_retries = 5
    for attempt in range(max_retries):
        try:
            async with sdk.ClaudeSDKClient(options=options) as client:
                await client.query(prompt, session_id=session_id)
                async for message in client.receive_response():
                    if isinstance(message, sdk.AssistantMessage):
                        for block in message.content:
                            if isinstance(block, sdk.TextBlock):
                                text = block.text.strip()
                                if text:
                                    assistant_lines.append(text)
                                    conversation_log.append({"role": "assistant", "text": text})
                            elif hasattr(block, "name"):
                                conversation_log.append({
                                    "role": "tool_call",
                                    "tool": getattr(block, "name", "?"),
                                    "input": str(getattr(block, "input", ""))[:500],
                                })
                    elif isinstance(message, sdk.ResultMessage):
                        final_session_id = message.session_id
                    else:
                        msg_type = type(message).__name__
                        msg_str = str(message)[:500] if len(str(message)) < 1000 else str(message)[:500] + "..."
                        conversation_log.append({"role": msg_type, "content": msg_str})
            break  # Success
        except Exception as exc:
            err_str = str(exc)
            is_retryable = any(s in err_str for s in ["429", "rate limit", "overloaded", "500", "502", "503"])
            if is_retryable and attempt < max_retries - 1:
                wait = 30 * (2 ** attempt)  # 30s, 60s, 120s, 240s
                print(f"[taiji] API error: {err_str[:200]}. Pausing {wait}s before retry ({attempt+1}/{max_retries})...")
                _time.sleep(wait)
                continue
            raise  # Non-retryable or exhausted retries

    return final_session_id, "\n".join(assistant_lines).strip(), conversation_log
