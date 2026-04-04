from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


def load_artifacts() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]:
    root = Path(__file__).resolve().parent
    world = json.loads((root / "world.json").read_text(encoding="utf-8"))
    candidate = json.loads((root / "candidate.json").read_text(encoding="utf-8"))
    witness = json.loads((root / "witness.json").read_text(encoding="utf-8"))
    derivation = (root / "derivation.md").read_text(encoding="utf-8")
    return world, candidate, witness, derivation


def derive_bounds(world: dict[str, Any], witness: dict[str, Any]) -> dict[str, float]:
    delta = float(witness["delta"])
    tau = float(witness["tau"])
    retention = float(witness["retention"])
    adaptation_gain = float(witness["adaptation_gain"])

    anchor_cosine = 1.0 - world["anchor_probe_horizon_steps"] * delta / 2.0
    tau_target = world["ema_tau_multiplier"] * delta
    tau_error = abs(tau - tau_target)
    transition_ratio = 1.0 + world["shift_sensitivity"] * delta / max(1e-9, retention + adaptation_gain)
    reduction_lower = (
        1.0
        - math.exp(-world["adaptation_window_steps"] * adaptation_gain * retention)
        - world["drift_penalty_scale"] * delta
    )
    return {
        "anchor_cosine": anchor_cosine,
        "tau_target": tau_target,
        "tau_error": tau_error,
        "transition_ratio_upper": transition_ratio,
        "reduction_lower": reduction_lower,
    }


def compile_candidate(candidate: dict[str, Any], witness: dict[str, Any]) -> dict[str, Any]:
    world, _, _, derivation = load_artifacts()
    bounds = derive_bounds(world, witness)
    return {
        "candidate": candidate,
        "witness": witness,
        "bounds": bounds,
        "derivation_excerpt": derivation.splitlines()[:8],
    }


if __name__ == "__main__":
    world, candidate, witness, _ = load_artifacts()
    print(json.dumps(
        {
            "world": world,
            "compiled": compile_candidate(candidate, witness),
        },
        indent=2,
        sort_keys=False,
    ))
