# self_improving_model

This is the first yin/yang-native environment.

Files the agents own:

- `prompt.md`
- `yang.py`
- `yin.py`

Files the shared orchestrator generates:

- `world.json`
- `rubric.md`
- `results.json`
- `history.ndjson`

Seed yin first:

```bash
python -m lab.dualloop seed --env-root envs/self_improving_model
```

Then run one round:

```bash
python -m lab.dualloop round --env-root envs/self_improving_model
```

To run it autoresearch-style forever:

```bash
python -m lab.dual_autoloop --env-root envs/self_improving_model --iterations -1 --resume-yang-session
```

In that mode:

- yang gets a turn every round
- yang uses the immutable `run_cycle` executor to run inside yin's current world
- if it fails, yang keeps going until it passes
- yin only wakes for a new edit after yang passes the current rubric
