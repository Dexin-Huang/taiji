"""
Shared schema helpers for the taiji runtime.
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[2]
CONTRACT_PATH: Final = ROOT / "contract.json"
CONTRACTS_LOG_PATH: Final = ROOT / "contracts.ndjson"
LEDGER_PATH: Final = ROOT / "ledger.ndjson"
REVIEW_EXEC_PATH: Final = ROOT / "lab" / "review_exec.py"

ALLOWED_GOALS: Final = {"min", "max"}
ALLOWED_OPS: Final = {"<=", "<", ">=", ">", "==", "!="}

Gate = dict[str, Any]
Contract = dict[str, Any]
Facts = dict[str, Any]
LedgerEntry = dict[str, Any]


@dataclass(frozen=True)
class ExperimentPaths:
    env_root: Path
    contract_path: Path
    contracts_log_path: Path
    ledger_path: Path
    review_exec_path: Path
    results_root: Path
    queue_root: Path
    model_path: Path
    train_path: Path
    tasks_path: Path
    program_path: Path
    review_path: Path


def iso_timestamp_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(path: Path | str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path | str, payload: dict[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def read_ndjson(path: Path | str) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.exists():
        return []
    records: list[dict[str, Any]] = []
    for raw_line in source.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        records.append(json.loads(line))
    return records


def append_ndjson(path: Path | str, record: dict[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=False) + "\n")


def resolve_env_root(env_root: Path | str | None = None) -> Path:
    if env_root is None:
        return ROOT
    return Path(env_root).resolve()


def run_slug_for_env(resolved: Path) -> Path:
    units_root = ROOT / "units"
    if resolved == ROOT:
        return Path("root")
    if resolved.is_relative_to(units_root):
        return resolved.relative_to(units_root)
    if resolved.is_relative_to(ROOT):
        return resolved.relative_to(ROOT)
    return Path(resolved.name)


def experiment_paths(env_root: Path | str | None = None) -> ExperimentPaths:
    resolved = resolve_env_root(env_root)
    run_root = ROOT / "runs" / run_slug_for_env(resolved) / "current"
    if resolved == ROOT:
        return ExperimentPaths(
            env_root=resolved,
            contract_path=CONTRACT_PATH,
            contracts_log_path=CONTRACTS_LOG_PATH,
            ledger_path=LEDGER_PATH,
            review_exec_path=REVIEW_EXEC_PATH,
            results_root=ROOT / "results",
            queue_root=ROOT / "queue",
            model_path=ROOT / "model.py",
            train_path=ROOT / "train.py",
            tasks_path=ROOT / "tasks.py",
            program_path=ROOT / "program.md",
            review_path=ROOT / "review.md",
        )
    return ExperimentPaths(
        env_root=resolved,
        contract_path=resolved / "contract.json",
        contracts_log_path=run_root / "contracts.ndjson",
        ledger_path=run_root / "ledger.ndjson",
        review_exec_path=resolved / "review_exec.py",
        results_root=run_root / "results",
        queue_root=run_root / "queue",
        model_path=resolved / "model.py",
        train_path=resolved / "train.py",
        tasks_path=resolved / "tasks.py",
        program_path=resolved / "program.md",
        review_path=resolved / "review.md",
    )


def normalize_gate(raw_gate: Gate) -> Gate:
    missing = [key for key in ("id", "metric", "op", "value") if key not in raw_gate]
    if missing:
        raise ValueError(f"Gate is missing required fields: {missing}")

    op = str(raw_gate["op"])
    if op not in ALLOWED_OPS:
        raise ValueError(f"Unsupported gate operator: {op}")

    return {
        "id": str(raw_gate["id"]),
        "metric": str(raw_gate["metric"]),
        "op": op,
        "value": raw_gate["value"],
    }


def normalize_contract(raw_contract: Contract) -> Contract:
    if "version" not in raw_contract:
        raise ValueError("Contract is missing version")

    raw_rank = raw_contract.get("rank", {})
    goal = str(raw_rank.get("goal", "min"))
    if goal not in ALLOWED_GOALS:
        raise ValueError(f"Unsupported rank goal: {goal}")

    contract = {
        "version": int(raw_contract["version"]),
        "rank": {
            "metric": str(raw_rank["metric"]),
            "goal": goal,
            "epsilon": float(raw_rank.get("epsilon", 0.0)),
        },
        "gates": [normalize_gate(gate) for gate in raw_contract.get("gates", [])],
        "latent_gates": [normalize_gate(gate) for gate in raw_contract.get("latent_gates", [])],
        "wake_rules": dict(raw_contract.get("wake_rules", {})),
    }

    gate_ids = [gate["id"] for gate in contract["gates"] + contract["latent_gates"]]
    if len(gate_ids) != len(set(gate_ids)):
        raise ValueError("Gate ids must be unique across active and latent gates")

    return contract


def copy_contract(contract: Contract) -> Contract:
    return normalize_contract(deepcopy(contract))


def load_contract(path: Path | str = CONTRACT_PATH) -> Contract:
    return normalize_contract(read_json(path))


def save_contract(contract: Contract, path: Path | str = CONTRACT_PATH) -> None:
    write_json(path, normalize_contract(contract))


def find_gate(contract: Contract, gate_id: str) -> Gate | None:
    for gate in contract.get("gates", []):
        if gate["id"] == gate_id:
            return gate
    for gate in contract.get("latent_gates", []):
        if gate["id"] == gate_id:
            return gate
    return None


def active_gate_ids(contract: Contract) -> set[str]:
    return {gate["id"] for gate in contract.get("gates", [])}
