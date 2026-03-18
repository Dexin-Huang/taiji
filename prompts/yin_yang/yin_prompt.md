Yin iteration {iteration}.

Own only {yin_file} and {yin_scratchpad}. Do not edit {yang_file} or any generated file.
You may read {yang_file} directly. Use both the implementation and the recorded evidence when you critique.
Preserve exactly two functions: world() and passes(results).
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

Old constraints stay. Add or tighten one orthogonal condition. The feasible set may shrink, but it must not jump to a different task. If the missing condition is not measurable in the current world, change world() first and encode the new requirement in passes(results).

Do not add decorative constraints. Add the smallest strict condition that removes the current loophole.
Do not reason at length in the assistant response. Keep the response to at most 3 short lines. Put any longer scratch work in {yin_scratchpad}.
