"""Unit scaffolding helpers for taiji."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import (
    DEFAULT_PROBLEM_KIND,
    DEFAULT_UNIT_KIND,
    MECHANISM_SEARCH_KIND,
    UNIT_CONFIG_NAME,
    load_unit_config,
    unit_config_for_problem_kind,
)
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


def default_unit_toml(
    unit_name: str,
    *,
    problem_kind: str | None = None,
    prompt_set: str | None = None,
) -> str:
    problem_kind = problem_kind or DEFAULT_PROBLEM_KIND
    prompt_set = prompt_set or (MECHANISM_SEARCH_KIND if problem_kind == MECHANISM_SEARCH_KIND else DEFAULT_UNIT_KIND)
    lines = [
        f'name = "{unit_name}"',
        f'kind = "{DEFAULT_UNIT_KIND}"',
        f'problem_kind = "{problem_kind}"',
        f'prompt_set = "{prompt_set}"',
    ]
    lines.append("")
    lines.append("[entry]")
    lines.append('prompt = "prompt.md"')
    if problem_kind == MECHANISM_SEARCH_KIND:
        lines.extend([
            'yang = "implementation.py"',
            'yin = "yin.py"',
            'candidate = "candidate.json"',
            'witness = "witness.json"',
            'derivation = "derivation.md"',
            'problem_spec = "problem_spec.md"',
            'counterexamples = "counterexamples.md"',
        ])
    else:
        lines.extend([
            'yang = "yang.py"',
            'yin = "yin.py"',
        ])
    return "\n".join(lines) + "\n"


def default_readme(unit_name: str, *, problem_kind: str = DEFAULT_PROBLEM_KIND) -> str:
    if problem_kind == MECHANISM_SEARCH_KIND:
        return (
            f"# {unit_name}\n\n"
            "Human input lives in `prompt.md`.\n"
            "The main mechanism entry point is `implementation.py`.\n\n"
            "Owned files:\n\n"
            "- `prompt.md`\n"
            "- `implementation.py`\n"
            "- `candidate.json`\n"
            "- `witness.json`\n"
            "- `derivation.md`\n"
            "- `yin.py`\n"
            "- `problem_spec.md`\n"
            "- `counterexamples.md`\n"
            "- `unit.toml`\n"
        )
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


def scaffold_paths(root: Path, config: Any) -> set[Path]:
    paths = {
        root / config.prompt_entry,
        root / config.yin_entry,
    }
    if config.problem_kind == MECHANISM_SEARCH_KIND:
        paths.update({
            root / config.yang_entry,
            root / config.candidate_entry,
            root / config.witness_entry,
            root / config.derivation_entry,
            root / config.problem_spec_entry,
            root / config.counterexamples_entry,
        })
    else:
        paths.add(root / config.yang_entry)
    return paths


def bootstrap_unit(
    unit_root: Path | str,
    *,
    prompt_text: str | None = None,
    problem_kind: str | None = None,
    prompt_set: str | None = None,
    force: bool = False,
    include_readme: bool = False,
    require_prompt: bool = False,
) -> dict[str, Any]:
    root = Path(unit_root).resolve()
    root.mkdir(parents=True, exist_ok=True)

    unit_config_path = root / UNIT_CONFIG_NAME
    existing_config = load_unit_config(root) if unit_config_path.exists() else None
    requested_override = problem_kind is not None or prompt_set is not None
    if unit_config_path.exists() and requested_override and not force:
        raise RuntimeError(
            f"{_relative(unit_config_path)} already exists. Use --force to reinitialize with a different problem_kind."
        )
    if unit_config_path.exists() and not requested_override:
        config = existing_config
    else:
        config = unit_config_for_problem_kind(root, prompt_set=prompt_set, problem_kind=problem_kind)
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
    removed: list[str] = []

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

    maybe_write(
        unit_config_path,
        default_unit_toml(root.name, problem_kind=config.problem_kind, prompt_set=config.prompt_set),
    )
    if config.problem_kind == MECHANISM_SEARCH_KIND:
        maybe_write(yang_path, template_text("implementation.py"))
        maybe_write(yin_path, template_text("yin.py"))
        maybe_write(root / config.candidate_entry, template_text("candidate.json"))
        maybe_write(root / config.witness_entry, template_text("witness.json"))
        maybe_write(root / config.derivation_entry, template_text("derivation.md"))
        maybe_write(root / config.problem_spec_entry, template_text("problem_spec.md"))
        maybe_write(root / config.counterexamples_entry, template_text("counterexamples.md"))
    else:
        maybe_write(yang_path, template_text("yang.py"))
        maybe_write(yin_path, template_text("yin.py"))
    if include_readme:
        maybe_write(readme_path, default_readme(root.name, problem_kind=config.problem_kind))

    if force and requested_override and existing_config is not None:
        obsolete_paths = scaffold_paths(root, existing_config) - scaffold_paths(root, config)
        for obsolete_path in sorted(obsolete_paths):
            if obsolete_path == unit_config_path:
                continue
            if obsolete_path.exists():
                obsolete_path.unlink()
                removed.append(_relative(obsolete_path))

    return {
        "unit_root": str(root),
        "created": created,
        "updated": updated,
        "removed": removed,
        "prompt_path": str(prompt_path),
        "unit_config_path": str(unit_config_path),
        "yang_path": str(yang_path),
        "yin_path": str(yin_path),
        "kind": config.kind,
        "problem_kind": config.problem_kind,
        "prompt_set": config.prompt_set,
        "readme_path": str(readme_path) if include_readme or readme_path.exists() else None,
    }
