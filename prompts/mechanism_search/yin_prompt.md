Yin iteration {iteration}.

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
