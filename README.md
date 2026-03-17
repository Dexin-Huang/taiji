# taiji

`taiji` is a yin/yang runtime for self-contained research units.

Each unit is a tiny authored surface:

- `prompt.md`
- `yang.py`
- `yin.py`
- `unit.yaml`
- optional `README.md`

Everything else is shared runtime or generated run state.

## Model

- `yang` owns `run() -> dict`
- `yin` owns `world() -> dict` and `passes(results) -> bool`
- the runtime is mechanical

`yin` defines the world and the law. `yang` searches for a solution inside that world. The runtime executes the cycle, records artifacts, and never invents criteria of its own.

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
      unit.yaml
      README.md
  runs/
    <unit>/
      current/
```

## Commands

Create a new unit from a concept:

```bash
python -m taiji.cycle new my_unit --goal "Develop a self-improving model architecture."
```

If you prefer, create only `units/my_unit/prompt.md` by hand. On the first `seed`, `round`, or `loop`, taiji will materialize `unit.yaml`, `yang.py`, and `yin.py` from templates.

Run one mechanical seed or round:

```bash
python -m taiji.cycle seed --unit-root units/persistent_state_model
python -m taiji.cycle round --unit-root units/persistent_state_model
python -m taiji.cycle status --unit-root units/persistent_state_model
```

Run the persistent yin/yang loop:

```bash
python -m taiji.loop --unit-root units/persistent_state_model --iterations -1 --resume-yang-session
```

Run the watchdog:

```bash
python -m taiji.watch --unit-root units/persistent_state_model
```

Stop the watchdog-managed loop:

```powershell
New-Item runs\persistent_state_model\current\queue\loop.stop -ItemType File -Force
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

Each active run materializes under `runs/<unit>/current/`:

- `world.json`
- `law.md`
- `results.json`
- `history.ndjson`
- `ideas.ndjson`
- `frontier.json`
- `yang_scratchpad.md`
- `yin_scratchpad.md`
- `queue/`

## Included Units

- `units/self_improving_model`
- `units/persistent_state_model`

## Notes

- `taiji.loop` exposes `WebFetch` and `Task` to both agents by default.
- Single-file ownership is enforced through edit hooks.
- Generated state stays out of `units/` so authored source remains clean.
- `taiji.loop` and `taiji.watch` require the Claude Agent SDK. Install the optional dependency with `pip install .[agent]`, or keep a local clone at `references/claude-agent-sdk-python`.

