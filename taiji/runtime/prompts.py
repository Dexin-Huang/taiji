"""Prompt template rendering for the taiji yin/yang loop."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .config import DEFAULT_PROBLEM_KIND, DEFAULT_UNIT_KIND, MECHANISM_SEARCH_KIND

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


def history_summary(paths: Any, limit: int = 20) -> str:
    if not paths.history_path.exists():
        return "No history yet."
    lines = [line.strip() for line in read_text(paths.history_path).splitlines() if line.strip()]
    if not lines:
        return "No history yet."
    payloads = [json.loads(line) for line in lines[-limit:]]
    parts = []
    for i, item in enumerate(payloads):
        phase = item.get("phase", "?")
        passed = item.get("passed")
        score = item.get("score", {})
        summary = score.get("summary", {}) if isinstance(score, dict) else {}
        # Show score details so yang can see progression
        score_str = ", ".join(f"{k}={v}" for k, v in summary.items()) if summary else "no score"
        parts.append(f"- [{i+1}] {phase}: passed={passed} | {score_str}")
    return "\n".join(parts)


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


def _is_mechanism_search(paths: Any) -> bool:
    config = getattr(paths, "config", None)
    return getattr(config, "problem_kind", DEFAULT_PROBLEM_KIND) == MECHANISM_SEARCH_KIND


def _artifact_path(paths: Any, entry_name: str, root: Path, *, fallback: Path | None = None) -> str:
    config = getattr(paths, "config", None)
    entry = getattr(config, entry_name, None)
    if isinstance(entry, str) and entry.strip():
        candidate = Path(entry)
        if candidate.is_absolute():
            return relative_artifact_path(candidate, root)
        return relative_artifact_path(getattr(paths, "run_root", root) / candidate, root)
    if fallback is not None:
        return relative_artifact_path(fallback, root)
    return ""


def _bullet_list(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items if item)


def prompt_context(paths: Any, root: Path, *, iteration: int | None = None) -> dict[str, str]:
    config = getattr(paths, "config", None)
    kind = getattr(config, "kind", DEFAULT_UNIT_KIND)
    problem_kind = getattr(config, "problem_kind", DEFAULT_PROBLEM_KIND)
    prompt_set = getattr(config, "prompt_set", "")
    implementation_file = _artifact_path(paths, "implementation_entry", root, fallback=getattr(paths, "yang_path", None))
    yang_candidate_file = _artifact_path(paths, "yang_candidate_entry", root, fallback=getattr(paths, "run_root", root) / "candidate.json")
    yang_witness_file = _artifact_path(paths, "yang_witness_entry", root, fallback=getattr(paths, "run_root", root) / "witness.json")
    yang_derivation_file = _artifact_path(paths, "yang_derivation_entry", root, fallback=getattr(paths, "run_root", root) / "derivation.md")
    yin_problem_spec_file = _artifact_path(paths, "yin_problem_spec_entry", root, fallback=getattr(paths, "run_root", root) / "problem_spec.md")
    yin_counterexamples_file = _artifact_path(paths, "yin_counterexamples_entry", root, fallback=getattr(paths, "run_root", root) / "counterexamples.md")
    candidate_file = _artifact_path(paths, "candidate_entry", root)
    witness_file = _artifact_path(paths, "witness_entry", root)
    derivation_file = _artifact_path(paths, "derivation_entry", root)
    problem_spec_file = _artifact_path(paths, "problem_spec_entry", root, fallback=getattr(paths, "yin_path", None))
    counterexamples_file = _artifact_path(paths, "counterexamples_entry", root)
    yang_owned_artifacts = [
        implementation_file,
        candidate_file,
        witness_file,
        derivation_file,
        relative_artifact_path(paths.yang_scratchpad_path, root),
        relative_artifact_path(paths.yang_notebook_path, root),
        relative_artifact_path(paths.workspace_path, root),
    ]
    yin_owned_artifacts = [
        relative_artifact_path(paths.yin_path, root),
        problem_spec_file,
        counterexamples_file,
        relative_artifact_path(paths.yin_scratchpad_path, root),
        relative_artifact_path(paths.yin_notebook_path, root),
    ]
    return {
        "iteration": "" if iteration is None else str(iteration),
        "problem_kind": problem_kind,
        "unit_kind": kind,
        "execution_kind": problem_kind,
        "prompt_set": prompt_set,
        "goal": prompt_text(paths),
        "law": law_text(paths),
        "world": latest_world(paths),
        "results": latest_results(paths),
        "history": history_summary(paths),
        "yang_file": relative_artifact_path(paths.yang_path, root),
        "yin_file": relative_artifact_path(paths.yin_path, root),
        "yang_scratchpad": relative_artifact_path(paths.yang_scratchpad_path, root),
        "yin_scratchpad": relative_artifact_path(paths.yin_scratchpad_path, root),
        "yang_notebook": relative_artifact_path(paths.yang_notebook_path, root),
        "yin_notebook": relative_artifact_path(paths.yin_notebook_path, root),
        "workspace": relative_artifact_path(paths.workspace_path, root),
        "world_file": relative_artifact_path(paths.world_path, root),
        "law_file": relative_artifact_path(paths.law_path, root),
        "results_file": relative_artifact_path(paths.results_path, root),
        "history_file": relative_artifact_path(paths.history_path, root),
        "ideas_file": relative_artifact_path(paths.ideas_path, root),
        "frontier_file": relative_artifact_path(paths.frontier_path, root),
        "implementation_file": implementation_file,
        "yang_candidate_entry": yang_candidate_file,
        "yang_witness_entry": yang_witness_file,
        "yang_derivation_entry": yang_derivation_file,
        "yin_problem_spec_entry": yin_problem_spec_file,
        "yin_counterexamples_entry": yin_counterexamples_file,
        "candidate_file": candidate_file,
        "witness_file": witness_file,
        "derivation_file": derivation_file,
        "problem_spec_file": problem_spec_file,
        "counterexamples_file": counterexamples_file,
        "yang_owned_artifacts": _bullet_list(yang_owned_artifacts),
        "yin_owned_artifacts": _bullet_list(yin_owned_artifacts),
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

Own {yang_file}, {yang_scratchpad}, {yang_notebook}, and everything under {workspace}/. Do not edit {yin_file} or any generated file.
You may read {yin_file}, {law_file}, {world_file}, {results_file}, and any generated artifact.

Memory:
- {yang_scratchpad}: this iteration's scratch (cleared each iteration)
- {yang_notebook}: persistent cross-iteration memory. READ IT FIRST. Write what you tried, why it failed, what to try next.
- {workspace}/: persistent Python modules you build. Import them in {yang_file} with `from workspace.module_name import X`. Create {workspace}/manifest.json to index your modules. These persist and accumulate across iterations — build a library of working components.
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


def default_mechanism_search_yang_prompt_template() -> str:
    return """Yang iteration {iteration}.

Own these artifacts and nothing else:
{yang_owned_artifacts}

Do not edit {yin_file}, {problem_spec_file}, {counterexamples_file}, or any generated file outside your ownership.
You may read {yin_file}, {problem_spec_file}, {counterexamples_file}, {law_file}, {world_file}, {results_file}, and any generated artifact.

Memory:
- {yang_scratchpad}: this iteration's scratch (cleared each iteration)
- {yang_notebook}: persistent cross-iteration memory. READ IT FIRST. Record the mechanism family, the witness you derived, the margins you hit, and the next tightening step.
- {workspace}/: persistent Python modules you build. Import them in {implementation_file} with `from workspace.module_name import X`.

Use run_cycle. It is the only authority on pass or fail.

If run_cycle returns passed=false, revise {implementation_file}, {candidate_file}, {witness_file}, and {derivation_file}, then run again.
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

Treat the task as a theorem search, not a coding contest. Derive the mechanism and witness first. The implementation is a compiled witness, not the search process itself.

Search for the smallest mechanism family that can satisfy the constraints simultaneously. Prefer analytic bounds over empirical claims. If you need to choose between a prettier architecture and a tighter witness, choose the tighter witness.

Write the candidate mechanism into {candidate_file}, the supporting bounds into {witness_file}, and the derivation into {derivation_file}. Keep the derivation compact and checkable.

You may use WebSearch, WebFetch, Bash, Task, and Codex when useful. Search the literature for relevant prior work. If you need prior run memory, use Task with the `run_librarian` agent for one concrete retrieval question.
The host evaluates {candidate_file}, {witness_file}, and {derivation_file} mechanically. Treat {implementation_file} as an optional compiled reference implementation, not as the primary search surface.

Do not reason at length in the assistant response. Keep the response to at most 3 short lines. Put any longer scratch work in {yang_scratchpad}.

End with 2-3 lines: hypothesis, mechanism change, latest pass/fail.
""".strip()


def default_yin_seed_prompt_template() -> str:
    return """Yin seed.

Own only {yin_file}, {yin_scratchpad}, and {yin_notebook}. Do not edit {yang_file} or any generated file.
You may read {yang_file}, prompt.md, and any generated artifact.
Preserve world(), passes(results), and optional score(results).
Use {yin_scratchpad} for this iteration's working notes (cleared each iteration).
Use {yin_notebook} for persistent cross-iteration memory: what yang tried, what loopholes you found, how you tightened, what to watch for next. READ IT FIRST. Write to it after every turn.

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


def default_mechanism_search_yin_seed_prompt_template() -> str:
    return """Yin seed.

Own these artifacts and nothing else:
{yin_owned_artifacts}

Do not edit {implementation_file}, {candidate_file}, {witness_file}, {derivation_file}, or any generated file outside your ownership.
You may read {implementation_file}, {candidate_file}, {witness_file}, {derivation_file}, prompt.md, and any generated artifact.
Preserve world(), passes(results), and optional score(results).
Use {yin_scratchpad} for this iteration's working notes (cleared each iteration).
Use {yin_notebook} for persistent cross-iteration memory: what mechanism families were tried, what failed, which witness gaps mattered, and how to tighten them. READ IT FIRST.
You may use WebSearch, WebFetch, Bash, Task, and Codex to research the problem domain and the mechanism family.

Goal:
{goal}

Assume the goal is achievable in principle. Your task is not to dismiss it. Your task is to define the smallest executable problem in which a mechanism can be judged mechanically.

Write the formal contract in {problem_spec_file}. Identify the minimal closed-form constraints the mechanism family must satisfy and the main loopholes a toy could exploit. Record the loopholes in {counterexamples_file}.

world() must specify a concrete environment, concrete metrics, and concrete resource limits. A run in this world must have an unambiguous outcome.

passes(results) must reject toys. Before you finalize it, identify at least three ways a toy could satisfy the letter of the goal while violating its substance. Encode defenses against all three. If the mechanism can be described with a witness, make the witness fields explicit and mechanically checkable.

If you define score(results), keep it public and mechanical. Return a dict with an ordered list of metrics under `order`, where each item has `name`, `value`, and `direction` (`min` or `max`). The host uses it only to keep or discard failing Yang attempts under the frozen law.
score(results) must also be robust to partial, failed, or empty results during host validation. Never raise, and never return NaN or infinity. Use finite fallback values when required evidence is missing.

Start strict. The first Yang attempt should fail unless it captures the real structure of the task.
Keep the assistant response to at most 3 short lines. Put longer scratch work in {yin_scratchpad}.
""".strip()


def default_yin_prompt_template() -> str:
    return """Yin iteration {iteration}.

Own only {yin_file}, {yin_scratchpad}, and {yin_notebook}. Do not edit {yang_file} or any generated file.
You may read {yang_file} directly. Use both the implementation and the recorded evidence when you critique.
Preserve world(), passes(results), and optional score(results).
Use {yin_scratchpad} for this iteration's working notes.
Use {yin_notebook} for persistent cross-iteration memory. READ IT FIRST. Record what yang tried, what loopholes you found, and how you tightened.

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


def default_mechanism_search_yin_prompt_template() -> str:
    return """Yin iteration {iteration}.

Own these artifacts and nothing else:
{yin_owned_artifacts}

Do not edit {implementation_file}, {candidate_file}, {witness_file}, or any generated file outside your ownership.
You may read {implementation_file}, {candidate_file}, {witness_file}, {derivation_file}, {problem_spec_file}, and any generated artifact.
Preserve world(), passes(results), and optional score(results).
Use {yin_scratchpad} for this iteration's working notes.
Use {yin_notebook} for persistent cross-iteration memory. READ IT FIRST. Record what Yang tried, what witness gap it used, and how you tightened the problem specification.
You may use WebSearch, WebFetch, Bash, Task, and Codex to inspect the mechanism and compare it to the current problem spec.

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

Then identify the loophole Yang used: the cheapest reason passed=true while the mechanism is still materially below that limit. Close exactly one gap.

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
        default_mechanism_search_yang_prompt_template() if _is_mechanism_search(paths) else default_yang_prompt_template(),
        prompt_context(paths, root, iteration=iteration),
    )


def yin_seed_prompt(paths: Any, root: Path) -> str:
    return render_prompt_template(
        paths.yin_seed_prompt_path,
        default_mechanism_search_yin_seed_prompt_template() if _is_mechanism_search(paths) else default_yin_seed_prompt_template(),
        prompt_context(paths, root),
    )


def yin_turn_prompt(paths: Any, root: Path, iteration: int) -> str:
    return render_prompt_template(
        paths.yin_prompt_path,
        default_mechanism_search_yin_prompt_template() if _is_mechanism_search(paths) else default_yin_prompt_template(),
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
