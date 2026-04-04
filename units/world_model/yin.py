from __future__ import annotations

import math
from typing import Any

EPS = 1e-9


def world() -> dict:
    """
    Mechanism-search world for streaming encoder drift.

    The data generator is fixed and public. The law does not ask Yang to
    brute-force a training run; it asks for a candidate mechanism plus a
    witness whose inequalities can be recomputed mechanically.
    """
    return {
        "seed": 42,
        "stream_family": "rotating_gaussians",
        "observation_dim": 8,
        "latent_dim": 4,
        "num_clusters": 4,
        "num_shifts": 10,
        "shift_degrees_min": 15,
        "shift_degrees_max": 30,
        "anchor_probe_horizon_steps": 20,
        "anchor_cosine_floor": 0.90,
        "anchor_cosine_ceiling": 0.98,
        "transition_ratio_max": 1.25,
        "reduction_min": 0.22,
        "ema_tau_multiplier": 6.0,
        "tau_consistency_tolerance": 0.01,
        "shift_sensitivity": 35.0,
        "adaptation_window_steps": 4.0,
        "drift_penalty_scale": 4.0,
        "retention_floor": 0.80,
        "min_latent_rank_ratio": 0.75,
        "max_component_count": 5,
        "allowed_mechanisms": [
            "ema_retained_fast_weights",
            "two_timescale_latent_carryover",
        ],
        "allowed_encoder_rules": [
            "ema_target",
            "lagged_teacher",
        ],
        "allowed_predictor_rules": [
            "linear_residual",
            "low_rank_linear",
        ],
        "allowed_fast_weight_rules": [
            "retained_delta",
            "retained_hebbian",
        ],
        "allowed_consolidation_rules": [
            "ema_consolidation",
            "sleep_replay_ema",
        ],
        "required_derivation_tags": [
            "bounded-drift",
            "tau-consistency",
            "transition-ratio",
            "reduction-bound",
        ],
    }


def _safe_float(value: Any, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(parsed):
        return fallback
    return parsed


def _safe_int(value: Any, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed


def _extract_artifacts(results: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], str]:
    if not isinstance(results, dict):
        return {}, {}, ""
    candidate = results.get("candidate")
    witness = results.get("witness")
    derivation = results.get("derivation")
    if not isinstance(candidate, dict):
        candidate = {}
    if not isinstance(witness, dict):
        witness = {}
    if not isinstance(derivation, str):
        derivation = ""
    return candidate, witness, derivation


def _family_match(candidate: dict[str, Any], spec: dict[str, Any]) -> float:
    checks = [
        candidate.get("mechanism") in spec["allowed_mechanisms"],
        candidate.get("encoder_rule") in spec["allowed_encoder_rules"],
        candidate.get("predictor_rule") in spec["allowed_predictor_rules"],
        candidate.get("fast_weight_rule") in spec["allowed_fast_weight_rules"],
        candidate.get("consolidation_rule") in spec["allowed_consolidation_rules"],
        candidate.get("carry_across_shift") is True,
        candidate.get("shared_latent_space") is True,
    ]
    return sum(1.0 for ok in checks if ok) / float(len(checks))


def _component_count(candidate: dict[str, Any]) -> int:
    return max(0, _safe_int(candidate.get("component_count"), 999))


def _latent_rank_ratio(candidate: dict[str, Any], spec: dict[str, Any]) -> float:
    latent_rank = max(0, _safe_int(candidate.get("latent_rank"), 0))
    latent_dim = max(1, _safe_int(spec.get("latent_dim"), 1))
    return float(latent_rank) / float(latent_dim)


def _derivation_coverage(derivation: str, spec: dict[str, Any]) -> float:
    tags = spec.get("required_derivation_tags", [])
    if not isinstance(tags, list) or not tags:
        return 1.0
    lowered = derivation.lower()
    matched = sum(1 for tag in tags if isinstance(tag, str) and tag in lowered)
    return float(matched) / float(len(tags))


def _derived_bounds(witness: dict[str, Any], spec: dict[str, Any]) -> dict[str, float]:
    delta = max(0.0, _safe_float(witness.get("delta"), 0.0))
    tau = max(0.0, _safe_float(witness.get("tau"), 0.0))
    retention = min(1.0, max(0.0, _safe_float(witness.get("retention"), 0.0)))
    adaptation_gain = max(0.0, _safe_float(witness.get("adaptation_gain"), 0.0))

    anchor_cosine = 1.0 - spec["anchor_probe_horizon_steps"] * delta / 2.0
    tau_target = spec["ema_tau_multiplier"] * delta
    tau_error = abs(tau - tau_target)
    transition_ratio = 1.0 + spec["shift_sensitivity"] * delta / max(EPS, retention + adaptation_gain)
    reduction_lower = (
        1.0
        - math.exp(-spec["adaptation_window_steps"] * adaptation_gain * retention)
        - spec["drift_penalty_scale"] * delta
    )
    return {
        "delta": delta,
        "tau": tau,
        "retention": retention,
        "adaptation_gain": adaptation_gain,
        "anchor_cosine": anchor_cosine,
        "tau_target": tau_target,
        "tau_error": tau_error,
        "transition_ratio_upper": transition_ratio,
        "reduction_lower": reduction_lower,
    }


def passes(results: dict) -> bool:
    """
    Accept only mechanisms with a mechanically checkable witness.

    The law recomputes the key inequalities instead of trusting reported
    metrics. This keeps the unit focused on solving the equations:

    - 0.90 <= 1 - H * delta / 2 <= 0.98
    - |tau - M * delta| <= tolerance
    - 1 + S * delta / (retention + adaptation_gain) <= 1.25
    - 1 - exp(-W * adaptation_gain * retention) - D * delta >= 0.22
    """
    if not isinstance(results, dict) or not bool(results.get("yang_contract_ok")):
        return False

    spec = world()
    candidate, witness, derivation = _extract_artifacts(results)
    family_match = _family_match(candidate, spec)
    if family_match < 1.0:
        return False

    component_count = _component_count(candidate)
    if component_count > spec["max_component_count"]:
        return False

    latent_rank_ratio = _latent_rank_ratio(candidate, spec)
    if latent_rank_ratio < spec["min_latent_rank_ratio"]:
        return False

    derivation_coverage = _derivation_coverage(derivation, spec)
    if derivation_coverage < 1.0:
        return False

    derived = _derived_bounds(witness, spec)
    if derived["anchor_cosine"] < spec["anchor_cosine_floor"]:
        return False
    if derived["anchor_cosine"] > spec["anchor_cosine_ceiling"]:
        return False
    if derived["tau_error"] > spec["tau_consistency_tolerance"]:
        return False
    if derived["transition_ratio_upper"] > spec["transition_ratio_max"]:
        return False
    if derived["reduction_lower"] < spec["reduction_min"]:
        return False
    if derived["retention"] < spec["retention_floor"]:
        return False

    return True


def score(results: dict) -> dict:
    """
    Lexicographic progress comparator over witness slack.

    Yang should first stay inside the allowed mechanism family, then tighten
    the anchor band, tau consistency, transition ratio, and reduction bound.
    """
    spec = world()
    candidate, witness, derivation = _extract_artifacts(results if isinstance(results, dict) else {})
    derived = _derived_bounds(witness, spec)

    family_match = _family_match(candidate, spec)
    component_count = _component_count(candidate)
    latent_rank_ratio = _latent_rank_ratio(candidate, spec)
    derivation_coverage = _derivation_coverage(derivation, spec)

    anchor_floor_margin = derived["anchor_cosine"] - spec["anchor_cosine_floor"]
    anchor_ceiling_margin = spec["anchor_cosine_ceiling"] - derived["anchor_cosine"]
    anchor_band_margin = min(anchor_floor_margin, anchor_ceiling_margin)
    tau_margin = spec["tau_consistency_tolerance"] - derived["tau_error"]
    transition_margin = spec["transition_ratio_max"] - derived["transition_ratio_upper"]
    reduction_margin = derived["reduction_lower"] - spec["reduction_min"]
    retention_margin = derived["retention"] - spec["retention_floor"]
    latent_rank_margin = latent_rank_ratio - spec["min_latent_rank_ratio"]
    simplicity_margin = float(spec["max_component_count"] - component_count)

    return {
        "order": [
            {"name": "family_match", "value": family_match, "direction": "max"},
            {"name": "anchor_band_margin", "value": anchor_band_margin, "direction": "max"},
            {"name": "tau_consistency_margin", "value": tau_margin, "direction": "max"},
            {"name": "transition_margin", "value": transition_margin, "direction": "max"},
            {"name": "reduction_margin", "value": reduction_margin, "direction": "max"},
            {"name": "retention_margin", "value": retention_margin, "direction": "max"},
            {"name": "latent_rank_margin", "value": latent_rank_margin, "direction": "max"},
            {"name": "derivation_coverage", "value": derivation_coverage, "direction": "max"},
            {"name": "simplicity_margin", "value": simplicity_margin, "direction": "max"},
        ],
        "summary": {
            "family_match": family_match,
            "anchor_cosine": derived["anchor_cosine"],
            "anchor_floor_margin": anchor_floor_margin,
            "anchor_ceiling_margin": anchor_ceiling_margin,
            "anchor_band_margin": anchor_band_margin,
            "tau": derived["tau"],
            "tau_target": derived["tau_target"],
            "tau_error": derived["tau_error"],
            "tau_consistency_margin": tau_margin,
            "transition_ratio_upper": derived["transition_ratio_upper"],
            "transition_margin": transition_margin,
            "reduction_lower": derived["reduction_lower"],
            "reduction_margin": reduction_margin,
            "retention": derived["retention"],
            "retention_margin": retention_margin,
            "adaptation_gain": derived["adaptation_gain"],
            "latent_rank_ratio": latent_rank_ratio,
            "latent_rank_margin": latent_rank_margin,
            "derivation_coverage": derivation_coverage,
            "component_count": component_count,
            "simplicity_margin": simplicity_margin,
        },
    }
