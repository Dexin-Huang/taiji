# Contributing

## Setup

```bash
git clone https://github.com/Dexin-Huang/taiji.git
cd taiji
pip install -e ".[agent]"
python -m taiji.smoke   # should pass
```

## Making changes

Branch off `main`. Run `python -m taiji.smoke` before opening a PR. Describe what changed and why in the PR body -- diffs alone aren't enough context.

## Naming conventions

These matter. Use them consistently:

- `unit_root`, not `env_root`
- `law`, not `rubric`
- `taiji` in all names, MCP servers, session slugs
- Yin owns `world()` and `passes()`. Yang owns `run()`. Don't blur the boundary.

## Bugs

[Open an issue.](https://github.com/Dexin-Huang/taiji/issues) Include steps to reproduce, what you expected, what actually happened, and your Python version.
