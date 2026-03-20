# Runs

This directory is for local run artifacts only.

Taiji copies each unit's `yin.py` and `yang.py` seeds into a run-local workspace here and writes all generated state under:

- `runs/<unit>/<run_id>/`
- `runs/<unit>/current.json`

Examples of local-only artifacts:

- materialized `world.json`, `law.md`, and `yin.snapshot.py`
- `results.json`, `history.ndjson`, `ideas.ndjson`, and `frontier.json`
- queue state, agent prompts, responses, diffs, and logs

These files should not be committed. The repo tracks only this README so the purpose of the folder is explicit.
