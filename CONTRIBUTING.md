# Contributing to Taiji

Thank you for your interest in contributing.

## Development Setup

1. Fork and clone the repo
2. Install dependencies: `pip install -e ".[agent]"`
3. Run smoke tests: `python -m taiji.smoke`

## Pull Request Process

1. Create a feature branch from `main`
2. Make your changes
3. Run `python -m taiji.smoke` and ensure everything passes
4. Submit a PR with a clear description of what changed and why

## Conventions

- `unit_root` not `env_root`
- `law` not `rubric`
- `taiji` in all names, MCP servers, session slugs
- Yin owns `world()` and `passes(results)`. Yang owns `run()`.
- The host is mechanical. No intelligence in the runtime.

## Reporting Bugs

Use [GitHub Issues](https://github.com/Dexin-Huang/taiji/issues). Include: steps to reproduce, expected behavior, actual behavior, Python version.
