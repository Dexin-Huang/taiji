Yang iteration {iteration}.

Own only {yang_file} and {yang_scratchpad}. Do not edit {yin_file} or any generated file.
You may read {yin_file}, {law_file}, {world_file}, {results_file}, and any generated artifact.
Use {yang_scratchpad} as private working notes. Put intermediate reasoning, candidate ideas, rejected directions, and partial plans there. Keep the assistant response terse.
Use run_cycle. It is the only authority on pass or fail.

If run_cycle returns passed=false, revise {yang_file} and run again.
If run_cycle returns passed=true, stop immediately.
If you hit the run_cycle call limit for this turn, summarize briefly and wait to be resumed.

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
Return a JSON object from {yang_file}. Nested dicts and lists are allowed. Put bulky traces in artifact files and return their paths.

A loophole that merely exploits passes() will trigger a stricter adaptive revision from yin. The shortest long-run path is an honest solution.

Do not reason at length in the assistant response. Keep the response to at most 3 short lines. Put any longer scratch work in {yang_scratchpad}.

End with 2-3 lines: hypothesis, change, latest pass/fail.
