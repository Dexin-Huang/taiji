"""Prompt template rendering for the taiji yin/yang loop."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


class SafePromptDict(dict[str, str]):
    """Dict that returns ``{key}`` for missing keys instead of raising."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def relative_artifact_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def history_summary(paths: Any, limit: int = 6) -> str:
    if not paths.history_path.exists():
        return "No history yet."
    lines = [line.strip() for line in read_text(paths.history_path).splitlines() if line.strip()]
    if not lines:
        return "No history yet."
    payloads = [json.loads(line) for line in lines[-limit:]]
    return "\n".join(
        f"- phase={item.get('phase')} passed={item.get('passed')} "
        f"world_keys={len(item.get('world', {}))} result_keys={len(item.get('results', {}))}"
        for item in payloads
    )


def law_text(paths: Any) -> str:
    if not paths.law_path.exists():
        return "No law yet."
    return read_text(paths.law_path).strip()


def prompt_text(paths: Any) -> str:
    return read_text(paths.prompt_path).strip()


def latest_results(paths: Any) -> str:
    if not paths.results_path.exists():
        return "{}"
    return read_text(paths.results_path).strip()


def latest_world(paths: Any) -> str:
    if not paths.world_path.exists():
        return "{}"
    return read_text(paths.world_path).strip()


def prompt_context(paths: Any, root: Path, *, iteration: int | None = None) -> dict[str, str]:
    return {
        "iteration": "" if iteration is None else str(iteration),
        "goal": prompt_text(paths),
        "law": law_text(paths),
        "world": latest_world(paths),
        "results": latest_results(paths),
        "history": history_summary(paths),
        "yang_file": relative_artifact_path(paths.yang_path, root),
        "yin_file": relative_artifact_path(paths.yin_path, root),
        "yang_scratchpad": relative_artifact_path(paths.yang_scratchpad_path, root),
        "yin_scratchpad": relative_artifact_path(paths.yin_scratchpad_path, root),
        "world_file": relative_artifact_path(paths.world_path, root),
        "law_file": relative_artifact_path(paths.law_path, root),
        "results_file": relative_artifact_path(paths.results_path, root),
        "history_file": relative_artifact_path(paths.history_path, root),
        "ideas_file": relative_artifact_path(paths.ideas_path, root),
        "frontier_file": relative_artifact_path(paths.frontier_path, root),
        "unit_root": relative_artifact_path(paths.unit_root, root),
        "run_root": relative_artifact_path(paths.run_root, root),
    }


def render_prompt_template(path: Path, default_template: str, context: dict[str, str]) -> str:
    template = read_text(path) if path.exists() else default_template
    return template.format_map(SafePromptDict(context)).strip()


def render_system_prompt(path: Path, default_prompt: str, context: dict[str, str]) -> str:
    template = read_text(path) if path.exists() else default_prompt
    return template.format_map(SafePromptDict(context)).strip()


# ---------------------------------------------------------------------------
# Default templates
# ---------------------------------------------------------------------------

def default_yang_prompt_template() -> str:
    return """Yang iteration {iteration}.

Own only {yang_file} and {yang_scratchpad}. Do not edit {yin_file} or any generated file.
You may read {yin_file}, {law_file}, {world_file}, {results_file}, and any generated artifact.
Use {yang_scratchpad} as private working notes. Put intermediate reasoning, candidate ideas, rejected directions, and partial plans there. Keep the assistant response terse.
Use run_cycle. It is the only authority on pass or fail.

If run_cycle returns passed=false, revise {yang_file} and run again.
If run_cycle returns passed=true, stop immediately.
If you hit the run_cycle call limit for this turn, summarize briefly and wait to be resumed.
Only a change that beats the current active candidate under the frozen law will be kept. Regressions are discarded mechanically.

Goal:
{goal}

Law:
{law}

World:
{world}

History:
{history}

Assume a passing solution exists. Do not spend turns arguing that the task is impossible. Search for the minimal executable construction that satisfies the current world and pass condition.

Prefer deletion over addition. Prefer a shorter mechanism over a longer one. Prefer a simpler invariant over a more baroque one. If two solutions pass, keep the simpler one.

You may use WebFetch and Task when useful, but only in service of a concrete change to {yang_file}. Do not call run_cycle on code you already expect to fail for trivial reasons.
If you need prior run memory, use Task with the `run_librarian` agent for one concrete retrieval question. Treat it as stateless: it rereads files fresh each time and should return only a compact answer plus paths.
Return a JSON object from {yang_file}. Nested dicts and lists are allowed. Put bulky traces in artifact files and return their paths.

A loophole that merely exploits passes() will trigger a stricter adaptive revision from yin. The shortest long-run path is an honest solution.

Do not reason at length in the assistant response. Keep the response to at most 3 short lines. Put any longer scratch work in {yang_scratchpad}.

End with 2-3 lines: hypothesis, change, latest pass/fail.
""".strip()


def default_yin_seed_prompt_template() -> str:
    return """Yin seed.

Own only {yin_file} and {yin_scratchpad}. Do not edit {yang_file} or any generated file.
You may read {yang_file}, prompt.md, and any generated artifact.
Preserve world(), passes(results), and optional score(results).
Use {yin_scratchpad} as private working notes. Keep the assistant response terse.

Goal:
{goal}

Assume the goal is achievable in principle. Your task is not to dismiss it. Your task is to define the smallest executable world in which the goal has a real optimum.

Identify the formal limit for this domain if one exists. If no closed-form bound exists, define the sharpest operational ideal this world can measure. Encode that ideal through world(), passes(results), and score(results) when useful. Do not write a manifesto.

world() must specify a concrete environment, concrete metrics, and concrete resource limits. A run in this world must have an unambiguous outcome.

passes(results) must reject toys. Before you finalize it, identify at least three ways a toy could satisfy the letter of the goal while violating its substance. Encode defenses against all three.

If you define score(results), keep it public and mechanical. Return a dict with an ordered list of metrics under `order`, where each item has `name`, `value`, and `direction` (`min` or `max`). The host uses it only to keep or discard failing yang attempts under the frozen law.
score(results) must also be robust to partial, failed, or empty results during host validation. Never raise, and never return NaN or infinity. Use finite fallback values when required evidence is missing.

Start strict. The first yang attempt should fail unless it captures the real structure of the task.
Keep the assistant response to at most 3 short lines. Put longer scratch work in {yin_scratchpad}.
""".strip()


def default_yin_prompt_template() -> str:
    return """Yin iteration {iteration}.

Own only {yin_file} and {yin_scratchpad}. Do not edit {yang_file} or any generated file.
You may read {yang_file} directly. Use both the implementation and the recorded evidence when you critique.
Preserve world(), passes(results), and optional score(results).
Use {yin_scratchpad} as private working notes. Put loophole analysis, candidate adaptive refinements, and rejected constraints there. Keep the assistant response terse.

Yang passed. Therefore the current bar is too low.

Goal:
{goal}

Law:
{law}

World:
{world}

Results:
{results}

History:
{history}

Assume the goal is achievable in principle. Do not argue that it is impossible. Identify the formal limit for this domain if one exists. If not, define the sharpest operational ideal this world can express.

Then identify the loophole yang used: the cheapest reason passed=true while the artifact is still materially below that limit. Close exactly one gap.

Old constraints stay. Add or tighten one orthogonal condition. The feasible set may shrink, but it must not jump to a different task. If the missing condition is not measurable in the current world, change world() first and encode the new requirement in passes(results). If score(results) exists, keep it aligned with the public law and use it only as an ordered progress comparator, not as a hidden second task.
If score(results) exists, it must remain total on partial, failed, or empty results too. Never raise, and never return NaN or infinity.

Do not add decorative constraints. Add the smallest strict condition that removes the current loophole.
Do not reason at length in the assistant response. Keep the response to at most 3 short lines. Put any longer scratch work in {yin_scratchpad}.
""".strip()


# ---------------------------------------------------------------------------
# Custom subagent prompts
# ---------------------------------------------------------------------------

def default_run_librarian_prompt_template() -> str:
    return """You are `run_librarian`, a read-only retrieval helper for one taiji run.

Treat every invocation as stateless. Do not rely on memory from prior subagent calls, prior sessions, or other runs. Read files fresh every time.

Stay scoped to this run:
- run root: {run_root}
- history: {history_file}
- ideas: {ideas_file}
- frontier: {frontier_file}

You may inspect files under {run_root} and, when explicitly relevant, the seed files under {unit_root}. Do not search unrelated runs unless the caller asks for a direct comparison.

Answer one concrete retrieval question at a time. Return at most 5 short bullets plus relevant file paths. Summarize; do not dump large file contents.

You are read-only. Never propose edits. Never call Task. Use only read/search tools.
""".strip()


# ---------------------------------------------------------------------------
# Convenience renderers
# ---------------------------------------------------------------------------

def yang_turn_prompt(paths: Any, root: Path, iteration: int) -> str:
    return render_prompt_template(
        paths.yang_prompt_path,
        default_yang_prompt_template(),
        prompt_context(paths, root, iteration=iteration),
    )


def yin_seed_prompt(paths: Any, root: Path) -> str:
    return render_prompt_template(
        paths.yin_seed_prompt_path,
        default_yin_seed_prompt_template(),
        prompt_context(paths, root),
    )


def yin_turn_prompt(paths: Any, root: Path, iteration: int) -> str:
    return render_prompt_template(
        paths.yin_prompt_path,
        default_yin_prompt_template(),
        prompt_context(paths, root, iteration=iteration),
    )


def run_librarian_prompt(paths: Any, root: Path) -> str:
    return default_run_librarian_prompt_template().format_map(
        SafePromptDict(prompt_context(paths, root)),
    )


def session_slug(path: Path, root: Path) -> str:
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        relative = path.name
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", relative.strip("/"))
    return slug or "unit"


def summarize_response(text: str, fallback: str) -> str:
    for raw_line in text.splitlines():
        line = raw_line.strip().lstrip("-*# ").strip()
        if not line:
            continue
        return re.sub(r"\s+", " ", line)[:240]
    return fallback

