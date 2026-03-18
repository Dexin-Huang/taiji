# taiji

`taiji` is a yin/yang runtime for self-contained research units.

Each unit is a tiny authored surface:

- `prompt.md`
- `yang.py`
- `yin.py`
- `unit.toml`
- optional `README.md`

These are seeds. A run copies `yang.py` and `yin.py` into `runs/.../<run_id>/` and edits only the run-local working copies.

## Model

- `yang` owns `run() -> dict`
- `yin` owns `world() -> dict`, `passes(results) -> bool`, and optional `score(results) -> dict`
- the runtime is mechanical

`yin` defines the world and the law. `yang` searches for a solution inside that world. The runtime executes the cycle, records artifacts, and never invents criteria of its own.

`yang.run()` returns a JSON object. Nested dicts and lists are allowed. `yin.passes(results)` may inspect that full JSON submission and `yang.py` itself.
If `yin.score(results)` is defined, the host uses it mechanically as a public keep/discard comparator among failing yang attempts under the frozen law snapshot.

The architecture is described directly in this README and in the source under `taiji/runtime/`.

## Layout

```text
taiji/
  taiji/
    runtime/
    templates/
  prompts/
    yin_yang/
  units/
    <unit>/
      prompt.md
      yang.py
      yin.py
      unit.toml
      README.md
  runs/
    <unit>/
      current.json
      <run_id>/
        yang.py
        yin.py
```

## Commands

Create a new unit from a concept:

```bash
python -m taiji.cycle new my_unit --goal "Develop a self-improving model architecture."
```

If you prefer, create only `units/my_unit/prompt.md` by hand. On the first `seed`, `round`, or `loop`, taiji will materialize `unit.toml`, `yang.py`, and `yin.py` from templates.

Run one mechanical seed or round:

```bash
python -m taiji.cycle seed --unit-root units/persistent_state_model --new
python -m taiji.cycle round --unit-root units/persistent_state_model
python -m taiji.cycle status --unit-root units/persistent_state_model
```

Run the lightweight kernel smoke checks:

```bash
python -m taiji.smoke
```

Run the persistent yin/yang loop:

```bash
python -m taiji.loop --unit-root units/persistent_state_model --new --iterations -1 --resume-yang-session
```

Run selection:

- `--new`: create a fresh run id and start from the unit seeds in a new run folder
- `--run-id <id>`: resume or target a specific existing run folder
- default behavior: resume the current run for that unit if one exists, otherwise create a new run id

Loop modes:

- `--mode adaptive` (default): yin may refine the world and acceptance condition after yang passes.
- `--mode fixed`: yin seeds once, then stays asleep while yang works against the fixed world and law.

Run the watchdog:

```bash
python -m taiji.watch --unit-root units/persistent_state_model --new
```

Stop the watchdog-managed loop:

```powershell
New-Item runs\persistent_state_model\<run_id>\queue\loop.stop -ItemType File -Force
```

## Prompt Sets

By default every unit uses the shared prompt set in `prompts/yin_yang/`.

A unit can override any of them with:

- `yang_prompt.override.md`
- `yin_prompt.override.md`
- `yin_seed_prompt.override.md`
- `yang_system_prompt.override.txt`
- `yin_system_prompt.override.txt`

## Run Artifacts

Each active run materializes under `runs/<unit>/<run_id>/`:

- `yang.py`
- `yin.py`
- `world.json`
- `law.md`
- `law_state.json`
- `yin.snapshot.py`
- `results.json`
- `history.ndjson`
- `ideas.ndjson`
- `frontier.json`
- `yang_scratchpad.md`
- `yin_scratchpad.md`
- `queue/`

`results.json` is the latest JSON submission from `yang.py`. It may contain nested evidence and artifact paths.
The `yang.py` and `yin.py` files under `runs/<unit>/<run_id>/` are the live working copies for that run. The unit files remain unchanged seeds.
`runs/<unit>/current.json` records which run id is currently active.

## Included Units

- `units/self_improving_model`
- `units/persistent_state_model`

## Notes

- `taiji.loop` exposes `WebFetch` and `Task` to both agents by default.
- Yang also gets a named read-only `run_librarian` custom agent via `Task`. It is scoped to the active run and instructed to behave statelessly across calls.
- Yang is selected harshly: the run keeps a new `yang.py` only when it beats the active candidate under the current frozen law. Otherwise the turn is discarded and the previous working copy is restored.
- Single-file ownership is enforced through edit hooks.
- Generated state stays out of `units/` so authored source remains clean.
- `taiji.loop` and `taiji.watch` require the Claude Agent SDK. Install the optional dependency with `pip install .[agent]`, or keep a local clone at `references/claude-agent-sdk-python`.

