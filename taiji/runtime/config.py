"""Unit configuration helpers for taiji."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .schema import ROOT

UNIT_CONFIG_NAME = "unit.toml"
DEFAULT_PROMPT_SET = "yin_yang"
SHARED_PROMPTS_ROOT = ROOT / "prompts"


@dataclass(frozen=True)
class UnitConfig:
    name: str
    kind: str
    prompt_set: str
    prompt_entry: str
    yang_entry: str
    yin_entry: str


def default_unit_config(unit_root: Path) -> UnitConfig:
    return UnitConfig(
        name=unit_root.name,
        kind="yin_yang",
        prompt_set=DEFAULT_PROMPT_SET,
        prompt_entry="prompt.md",
        yang_entry="yang.py",
        yin_entry="yin.py",
    )


def _read_config_payload(config_path: Path) -> dict[str, Any]:
    try:
        payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise RuntimeError(f"Invalid {UNIT_CONFIG_NAME}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{UNIT_CONFIG_NAME} root must be a table")
    return payload


def _read_table(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise RuntimeError(f"{UNIT_CONFIG_NAME} [{key}] must be a table")
    return value


def load_unit_config(unit_root: Path) -> UnitConfig:
    config_path = unit_root / UNIT_CONFIG_NAME
    if not config_path.exists():
        return default_unit_config(unit_root)

    payload = _read_config_payload(config_path)
    entry = _read_table(payload, "entry")

    config = default_unit_config(unit_root)
    kind = str(payload.get("kind", config.kind)).strip() or config.kind
    if kind != "yin_yang":
        raise RuntimeError(f"Unsupported unit kind {kind!r}; expected 'yin_yang'")

    prompt_set = str(payload.get("prompt_set", config.prompt_set)).strip() or config.prompt_set
    prompt_entry = str(entry.get("prompt", config.prompt_entry)).strip() or config.prompt_entry
    yang_entry = str(entry.get("yang", config.yang_entry)).strip() or config.yang_entry
    yin_entry = str(entry.get("yin", config.yin_entry)).strip() or config.yin_entry

    return UnitConfig(
        name=str(payload.get("name", config.name)).strip() or config.name,
        kind=kind,
        prompt_set=prompt_set,
        prompt_entry=prompt_entry,
        yang_entry=yang_entry,
        yin_entry=yin_entry,
    )


def resolve_prompt_path(root: Path, override_name: str, shared_name: str, prompt_set: str) -> Path:
    override_path = root / override_name
    if override_path.exists():
        return override_path
    return SHARED_PROMPTS_ROOT / prompt_set / shared_name
