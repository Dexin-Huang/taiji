"""Unit configuration helpers for taiji."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .schema import ROOT

UNIT_CONFIG_NAME = "unit.toml"
DEFAULT_UNIT_KIND = "yin_yang"
DEFAULT_PROBLEM_KIND = "program_search"
MECHANISM_SEARCH_KIND = "mechanism_search"
DEFAULT_PROMPT_SET = DEFAULT_UNIT_KIND
MECHANISM_SEARCH_PROMPT_SET = MECHANISM_SEARCH_KIND
SHARED_PROMPTS_ROOT = ROOT / "prompts"


@dataclass(frozen=True)
class UnitConfig:
    name: str
    kind: str
    problem_kind: str
    prompt_set: str
    prompt_entry: str
    yang_entry: str
    yin_entry: str
    implementation_entry: str
    candidate_entry: str
    witness_entry: str
    derivation_entry: str
    problem_spec_entry: str
    counterexamples_entry: str
    yang_candidate_entry: str
    yang_witness_entry: str
    yang_derivation_entry: str
    yin_problem_spec_entry: str
    yin_counterexamples_entry: str


def normalize_problem_kind(problem_kind: str | None) -> str:
    normalized = str(problem_kind or DEFAULT_PROBLEM_KIND).strip() or DEFAULT_PROBLEM_KIND
    if normalized not in {DEFAULT_PROBLEM_KIND, MECHANISM_SEARCH_KIND}:
        raise RuntimeError(
            f"Unsupported problem_kind {normalized!r}; expected {DEFAULT_PROBLEM_KIND!r} or {MECHANISM_SEARCH_KIND!r}"
        )
    return normalized


def _canonical_kind_and_problem_kind(
    raw_kind: str | None,
    raw_problem_kind: str | None,
) -> tuple[str, str]:
    kind = str(raw_kind or DEFAULT_UNIT_KIND).strip() or DEFAULT_UNIT_KIND
    if kind not in {DEFAULT_UNIT_KIND, MECHANISM_SEARCH_KIND}:
        raise RuntimeError(f"Unsupported unit kind {kind!r}; expected {DEFAULT_UNIT_KIND!r}")

    inferred_problem_kind = raw_problem_kind
    if kind == MECHANISM_SEARCH_KIND:
        if inferred_problem_kind is not None and str(inferred_problem_kind).strip() not in {"", MECHANISM_SEARCH_KIND}:
            raise RuntimeError(
                f"Inconsistent config: legacy kind {MECHANISM_SEARCH_KIND!r} requires "
                f"problem_kind {MECHANISM_SEARCH_KIND!r}."
            )
        inferred_problem_kind = MECHANISM_SEARCH_KIND

    return DEFAULT_UNIT_KIND, normalize_problem_kind(inferred_problem_kind)


def unit_config_for_problem_kind(
    unit_root: Path,
    *,
    prompt_set: str | None = None,
    problem_kind: str | None = None,
) -> UnitConfig:
    kind, problem_kind = _canonical_kind_and_problem_kind(DEFAULT_UNIT_KIND, problem_kind)

    if problem_kind == MECHANISM_SEARCH_KIND:
        prompt_set = str(prompt_set).strip() if prompt_set is not None else MECHANISM_SEARCH_PROMPT_SET
        prompt_set = prompt_set or MECHANISM_SEARCH_PROMPT_SET
        yang_entry = "implementation.py"
    else:
        prompt_set = str(prompt_set).strip() if prompt_set is not None else DEFAULT_PROMPT_SET
        prompt_set = prompt_set or DEFAULT_PROMPT_SET
        yang_entry = "yang.py"

    return UnitConfig(
        name=unit_root.name,
        kind=kind,
        problem_kind=problem_kind,
        prompt_set=prompt_set,
        prompt_entry="prompt.md",
        yang_entry=yang_entry,
        yin_entry="yin.py",
        implementation_entry="implementation.py" if problem_kind == MECHANISM_SEARCH_KIND else yang_entry,
        candidate_entry="candidate.json",
        witness_entry="witness.json",
        derivation_entry="derivation.md",
        problem_spec_entry="problem_spec.md",
        counterexamples_entry="counterexamples.md",
        yang_candidate_entry="candidate.json",
        yang_witness_entry="witness.json",
        yang_derivation_entry="derivation.md",
        yin_problem_spec_entry="problem_spec.md",
        yin_counterexamples_entry="counterexamples.md",
    )


def default_unit_config(unit_root: Path) -> UnitConfig:
    return unit_config_for_problem_kind(unit_root)


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

    kind, problem_kind = _canonical_kind_and_problem_kind(
        payload.get("kind", DEFAULT_UNIT_KIND),
        payload.get("problem_kind"),
    )
    config = unit_config_for_problem_kind(
        unit_root,
        prompt_set=payload.get("prompt_set"),
        problem_kind=problem_kind,
    )
    prompt_set = str(payload.get("prompt_set", config.prompt_set)).strip() or config.prompt_set
    prompt_entry = str(entry.get("prompt", config.prompt_entry)).strip() or config.prompt_entry
    yang_entry = str(entry.get("yang", config.yang_entry)).strip() or config.yang_entry
    yin_entry = str(entry.get("yin", config.yin_entry)).strip() or config.yin_entry
    implementation_entry = str(entry.get("implementation", entry.get("yang", config.implementation_entry))).strip() or config.implementation_entry
    candidate_entry = str(entry.get("candidate", config.candidate_entry)).strip() or config.candidate_entry
    witness_entry = str(entry.get("witness", config.witness_entry)).strip() or config.witness_entry
    derivation_entry = str(entry.get("derivation", config.derivation_entry)).strip() or config.derivation_entry
    problem_spec_entry = str(entry.get("problem_spec", config.problem_spec_entry)).strip() or config.problem_spec_entry
    counterexamples_entry = str(entry.get("counterexamples", config.counterexamples_entry)).strip() or config.counterexamples_entry
    yang_candidate_entry = str(entry.get("yang_candidate_entry", entry.get("candidate", config.yang_candidate_entry))).strip() or config.yang_candidate_entry
    yang_witness_entry = str(entry.get("yang_witness_entry", entry.get("witness", config.yang_witness_entry))).strip() or config.yang_witness_entry
    yang_derivation_entry = str(entry.get("yang_derivation_entry", entry.get("derivation", config.yang_derivation_entry))).strip() or config.yang_derivation_entry
    yin_problem_spec_entry = str(entry.get("yin_problem_spec_entry", entry.get("problem_spec", config.yin_problem_spec_entry))).strip() or config.yin_problem_spec_entry
    yin_counterexamples_entry = str(entry.get("yin_counterexamples_entry", entry.get("counterexamples", config.yin_counterexamples_entry))).strip() or config.yin_counterexamples_entry

    return UnitConfig(
        name=str(payload.get("name", config.name)).strip() or config.name,
        kind=kind,
        problem_kind=problem_kind,
        prompt_set=prompt_set,
        prompt_entry=prompt_entry,
        yang_entry=yang_entry,
        yin_entry=yin_entry,
        implementation_entry=implementation_entry,
        candidate_entry=candidate_entry,
        witness_entry=witness_entry,
        derivation_entry=derivation_entry,
        problem_spec_entry=problem_spec_entry,
        counterexamples_entry=counterexamples_entry,
        yang_candidate_entry=yang_candidate_entry,
        yang_witness_entry=yang_witness_entry,
        yang_derivation_entry=yang_derivation_entry,
        yin_problem_spec_entry=yin_problem_spec_entry,
        yin_counterexamples_entry=yin_counterexamples_entry,
    )


def resolve_prompt_path(root: Path, override_name: str, shared_name: str, prompt_set: str) -> Path:
    override_path = root / override_name
    if override_path.exists():
        return override_path
    return SHARED_PROMPTS_ROOT / prompt_set / shared_name
