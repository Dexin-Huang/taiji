Yin seed.

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
