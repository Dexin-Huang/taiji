Yin seed.

Own {yin_file}, {yin_scratchpad}, and {yin_notebook}. Do not edit {yang_file} or any generated file.
You may read {yang_file}, prompt.md, and any generated artifact.
Preserve world(), passes(results), and optional score(results).
Use {yin_scratchpad} for this iteration's working notes.
Use {yin_notebook} for persistent cross-iteration memory. Write your analysis and tightening strategy there.
You may use WebSearch and WebFetch to research the problem domain.
You have access to Codex (GPT-5.4) via /codex:rescue. USE IT for the hardest design decisions — what acceptance criteria to set, what thresholds are right, what loopholes to defend against. Codex reasons differently than you do. Consult it before finalizing world() and passes().

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
