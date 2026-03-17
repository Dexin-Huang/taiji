# persistent_state_model

This environment pressures persistent hidden state and online improvement together.

Files the agents own:

- `prompt.md`
- `yang.py`
- `yin.py`

Shared prompt templates live in [prompts/yin_yang](D:/Projects/autoratchet/prompts/yin_yang):

- [yang_prompt.md](D:/Projects/autoratchet/prompts/yin_yang/yang_prompt.md)
- [yin_prompt.md](D:/Projects/autoratchet/prompts/yin_yang/yin_prompt.md)
- [yin_seed_prompt.md](D:/Projects/autoratchet/prompts/yin_yang/yin_seed_prompt.md)
- [yang_system_prompt.txt](D:/Projects/autoratchet/prompts/yin_yang/yang_system_prompt.txt)
- [yin_system_prompt.txt](D:/Projects/autoratchet/prompts/yin_yang/yin_system_prompt.txt)

If this env needs custom prompts, add env-local overrides:

- `yang_prompt.override.md`
- `yin_prompt.override.md`
- `yin_seed_prompt.override.md`
- `yang_system_prompt.override.txt`
- `yin_system_prompt.override.txt`

The editable prompt templates support placeholders such as:

- `{iteration}`
- `{goal}`
- `{rubric}`
- `{world}`
- `{results}`
- `{history}`
- `{yang_file}`
- `{yin_file}`

Files the shared orchestrator generates:

- `world.json`
- `rubric.md`
- `results.json`
- `history.ndjson`

Seed yin first:

```bash
python -m lab.dualloop seed --env-root envs/persistent_state_model
```

Run one round:

```bash
python -m lab.dualloop round --env-root envs/persistent_state_model
```

Run it autoresearch-style forever:

```bash
python -m lab.dual_autoloop --env-root envs/persistent_state_model --iterations -1 --resume-yang-session
```

In this world:

- yin defines a chunked latent dynamical system
- yang must adapt on early chunks
- yang is judged on held-out transfer across episodes from the same system
- yang is also judged on whether carrying hidden state helps on later chunks of the same stream
