<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="assets/logo.svg">
    <img alt="Taiji" src="assets/logo.svg" width="160">
  </picture>
</p>

<h1 align="center">Taiji</h1>

<p align="center">
  <strong>Two agents. One evolving truth.</strong>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.11+-3776AB.svg?logo=python&logoColor=white" alt="Python 3.11+"></a>
  <a href="https://pypi.org/project/claude-agent-sdk/"><img src="https://img.shields.io/badge/Claude-Agent%20SDK-cc785c.svg" alt="Claude Agent SDK"></a>
</p>

---

Taiji is an adversarial co-evolution runtime for autonomous research. Two AI agents -- **yin** and **yang** -- alternate in a loop: yin defines the problem, yang searches for a solution, and when yang succeeds, yin tightens the constraints. The problem and the solution evolve together until convergence.

> *Yin writes the law. Yang finds a way. When yang passes, yin raises the bar.*

## How It Works

```
                    ┌─────────────────────────┐
                    │      Seed Phase          │
                    │  Yin defines world()     │
                    │  and passes(results)     │
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
              ┌────►│      Yang Turn           │
              │     │  Search for a solution   │
              │     │  that satisfies the law  │
              │     └────────────┬────────────┘
              │                  │
              │          passed? │
              │       ┌─────────┴─────────┐
              │       │ no                │ yes
              │       ▼                   ▼
              │    retry            ┌───────────┐
              │                     │  Yin Turn  │
              │                     │  Find the  │
              │                     │  loophole. │
              │                     │  Tighten   │
              │                     │  one       │
              │                     │  constraint│
              │                     └─────┬─────┘
              │                           │
              │                  changed? │
              │                ┌──────────┴──────┐
              │                │ yes              │ no
              └────────────────┘           converged ■
```

**Yin** owns the world and the law: `world() -> dict`, `passes(results) -> bool`, and optional `score(results) -> dict`.

**Yang** owns the search: `run() -> dict` -- a JSON submission tested against the frozen law.

**The host** is purely mechanical. It executes the cycle, records artifacts, and never invents criteria of its own.

## Quick Start

```bash
pip install -e .

# Create a new research unit
python -m taiji.cycle new my_unit --goal "Build a self-improving model."

# Seed the initial law
python -m taiji.cycle seed --unit-root units/my_unit --new

# Run the full yin/yang loop (requires Claude Agent SDK)
pip install -e ".[agent]"
python -m taiji.loop --unit-root units/my_unit --new --iterations -1
```

## Architecture

```
taiji/
  taiji/runtime/
    schema.py         Filesystem helpers, dynamic module loading
    cycle.py          Core yin/yang mechanics (no SDK dependency)
    law.py            Immutable law snapshots, validation, materialization
    prompts.py        Prompt templates, rendering, context assembly
    ideas.py          Idea tracking, frontier materialization
    agents.py         Claude Agent SDK turn execution, edit hooks
    loop.py           Main loop orchestrator, CLI
    watch.py          Supervisor process (restart on crash)
  prompts/yin_yang/   Shared prompt templates
  units/              Experiment definitions (yin.py, yang.py, prompt.md)
  runs/               Generated run artifacts (gitignored)
```

<details>
<summary><strong>Run artifacts</strong></summary>

Each run materializes under `runs/<unit>/<run_id>/`:

| File | Purpose |
|------|---------|
| `yang.py`, `yin.py` | Live working copies (unit seeds stay untouched) |
| `world.json` | Materialized world from `yin.world()` |
| `law.md` | Frozen law snapshot with source and world |
| `results.json` | Latest yang submission |
| `history.ndjson` | Full iteration history |
| `ideas.ndjson` | Idea records with tags and lineage |
| `frontier.json` | Summary: latest idea, recent attempts, tag counts |
| `queue/` | Per-iteration artifacts and control files |

</details>

<details>
<summary><strong>Loop modes and run selection</strong></summary>

**Run selection:**
- `--new` &mdash; fresh run from unit seeds
- `--run-id <id>` &mdash; resume a specific run
- Default &mdash; resume current run, or create new

**Modes:**
- `--mode adaptive` (default) &mdash; yin refines constraints after yang passes
- `--mode fixed` &mdash; yin seeds once, yang works against a frozen law

**Watchdog:**
```bash
python -m taiji.watch --unit-root units/my_unit --new
```

</details>

<details>
<summary><strong>Prompt overrides</strong></summary>

Units use the shared prompt set in `prompts/yin_yang/` by default. Override any template by placing these in your unit directory:

- `yang_prompt.override.md`
- `yin_prompt.override.md`
- `yin_seed_prompt.override.md`
- `yang_system_prompt.override.txt`
- `yin_system_prompt.override.txt`

</details>

## Design Principles

- **The host is mechanical.** No intelligence in the runtime. All intelligence emerges from the agents.
- **File ownership is enforced.** Yang can only edit `yang.py`. Yin can only edit `yin.py`. Edit hooks prevent boundary crossing.
- **Yang is selected harshly.** A new `yang.py` is kept only when it beats the current candidate under the frozen law. Otherwise the turn is discarded.
- **Loopholes get caught.** Yin identifies how yang exploited `passes()` and tightens exactly one orthogonal constraint per round.
- **Everything is an artifact.** State is reconstructed from `history.ndjson` and `ideas.ndjson`. Nothing is in-memory only.

## Versioning

Taiji is pre-1.0. The API may change between minor versions. Stability of the core cycle mechanics (`world`, `passes`, `run`) is a priority.

## License

[MIT](LICENSE)
