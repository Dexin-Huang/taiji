"""Unit scaffolding helpers for taiji."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import UNIT_CONFIG_NAME, load_unit_config
from .schema import ROOT

TEMPLATES_ROOT = ROOT / "taiji" / "templates"


def resolve_new_unit_root(target: str | Path) -> Path:
    candidate = Path(target)
    if candidate.is_absolute():
        return candidate.resolve()
    if candidate.parts and candidate.parts[0] == "units":
        return (ROOT / candidate).resolve()
    if len(candidate.parts) == 1:
        return (ROOT / "units" / candidate).resolve()
    return (ROOT / candidate).resolve()


def default_prompt_text() -> str:
    return "# Goal\n\nDescribe the research goal for this unit.\n"


def normalize_prompt_text(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return default_prompt_text()
    if stripped.startswith("#"):
        return stripped + "\n"
    return f"# Goal\n\n{stripped}\n"


def default_unit_toml(unit_name: str) -> str:
    return (
        f'name = "{unit_name}"\n'
        'kind = "yin_yang"\n'
        'prompt_set = "yin_yang"\n\n'
        "[entry]\n"
        'prompt = "prompt.md"\n'
        'yang = "yang.py"\n'
        'yin = "yin.py"\n'
    )


def default_readme(unit_name: str) -> str:
    return (
        f"# {unit_name}\n\n"
        "Human input lives in `prompt.md`.\n\n"
        "Owned files:\n\n"
        "- `prompt.md`\n"
        "- `yang.py`\n"
        "- `yin.py`\n"
        "- `unit.toml`\n"
    )


def template_text(filename: str) -> str:
    return (TEMPLATES_ROOT / filename).read_text(encoding="utf-8")


def _relative(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def bootstrap_unit(
    unit_root: Path | str,
    *,
    prompt_text: str | None = None,
    force: bool = False,
    include_readme: bool = False,
    require_prompt: bool = False,
) -> dict[str, Any]:
    root = Path(unit_root).resolve()
    root.mkdir(parents=True, exist_ok=True)

    unit_config_path = root / UNIT_CONFIG_NAME
    config = load_unit_config(root)
    prompt_path = root / config.prompt_entry
    yang_path = root / config.yang_entry
    yin_path = root / config.yin_entry
    readme_path = root / "README.md"

    if not prompt_path.exists():
        if prompt_text is not None:
            prompt_path.write_text(normalize_prompt_text(prompt_text), encoding="utf-8")
        elif require_prompt:
            raise RuntimeError(
                f"{_relative(prompt_path)} is missing. Create prompt.md or run `python -m taiji.cycle new <name> --goal \"...\"`."
            )
        else:
            prompt_path.write_text(default_prompt_text(), encoding="utf-8")
    elif force and prompt_text is not None:
        prompt_path.write_text(normalize_prompt_text(prompt_text), encoding="utf-8")

    created: list[str] = []
    updated: list[str] = []

    def maybe_write(path: Path, text: str) -> None:
        nonlocal created, updated
        existed = path.exists()
        if existed and not force:
            return
        path.write_text(text, encoding="utf-8")
        rel = _relative(path)
        if existed:
            updated.append(rel)
        else:
            created.append(rel)

    maybe_write(unit_config_path, default_unit_toml(root.name))
    maybe_write(yang_path, template_text("yang.py"))
    maybe_write(yin_path, template_text("yin.py"))
    if include_readme:
        maybe_write(readme_path, default_readme(root.name))

    return {
        "unit_root": str(root),
        "created": created,
        "updated": updated,
        "prompt_path": str(prompt_path),
        "unit_config_path": str(unit_config_path),
        "yang_path": str(yang_path),
        "yin_path": str(yin_path),
        "readme_path": str(readme_path) if include_readme or readme_path.exists() else None,
    }
