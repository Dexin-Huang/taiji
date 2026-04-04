"""Operational frontier state for the taiji loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .schema import ROOT, iso_timestamp_now, read_json, write_json

FRONTIER_SCHEMA_VERSION = 1


def _relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT).as_posix())
    except ValueError:
        return str(path.resolve())


@dataclass(frozen=True)
class CandidateEnvelope:
    candidate_id: str
    branch_id: str
    parent_ids: tuple[str, ...] = ()
    artifact_refs: dict[str, str] = field(default_factory=dict)
    law_ref: dict[str, Any] = field(default_factory=dict)
    eval_refs: tuple[str, ...] = ()
    cost_ledger_ref: str | None = None
    created_at: str = ""
    last_updated_at: str = ""
    status: str = "active"

    def to_json(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "branch_id": self.branch_id,
            "parent_ids": list(self.parent_ids),
            "artifact_refs": dict(self.artifact_refs),
            "law_ref": dict(self.law_ref),
            "eval_refs": list(self.eval_refs),
            "cost_ledger_ref": self.cost_ledger_ref,
            "created_at": self.created_at,
            "last_updated_at": self.last_updated_at,
            "status": self.status,
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "CandidateEnvelope":
        return cls(
            candidate_id=str(raw.get("candidate_id", "")).strip(),
            branch_id=str(raw.get("branch_id", "")).strip(),
            parent_ids=tuple(str(item) for item in raw.get("parent_ids", []) if str(item).strip()),
            artifact_refs={
                str(key): str(value)
                for key, value in dict(raw.get("artifact_refs", {})).items()
                if str(key).strip() and str(value).strip()
            },
            law_ref=dict(raw.get("law_ref", {})),
            eval_refs=tuple(str(item) for item in raw.get("eval_refs", []) if str(item).strip()),
            cost_ledger_ref=(
                str(raw.get("cost_ledger_ref")).strip()
                if raw.get("cost_ledger_ref") not in {None, ""}
                else None
            ),
            created_at=str(raw.get("created_at", "")).strip(),
            last_updated_at=str(raw.get("last_updated_at", "")).strip(),
            status=str(raw.get("status", "active")).strip() or "active",
        )


@dataclass(frozen=True)
class FrontierMember:
    candidate_id: str
    status: str = "active"
    current_tier: str = "tier1"
    last_eval_ref: str | None = None
    novelty: float = 0.0
    simplicity: float = 0.0
    robustness: float = 0.0
    cost_spent: float = 0.0

    def to_json(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "status": self.status,
            "current_tier": self.current_tier,
            "last_eval_ref": self.last_eval_ref,
            "novelty": self.novelty,
            "simplicity": self.simplicity,
            "robustness": self.robustness,
            "cost_spent": self.cost_spent,
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "FrontierMember":
        return cls(
            candidate_id=str(raw.get("candidate_id", "")).strip(),
            status=str(raw.get("status", "active")).strip() or "active",
            current_tier=str(raw.get("current_tier", "tier1")).strip() or "tier1",
            last_eval_ref=(
                str(raw.get("last_eval_ref")).strip()
                if raw.get("last_eval_ref") not in {None, ""}
                else None
            ),
            novelty=float(raw.get("novelty", 0.0) or 0.0),
            simplicity=float(raw.get("simplicity", 0.0) or 0.0),
            robustness=float(raw.get("robustness", 0.0) or 0.0),
            cost_spent=float(raw.get("cost_spent", 0.0) or 0.0),
        )


@dataclass(frozen=True)
class FrontierState:
    schema_version: int = FRONTIER_SCHEMA_VERSION
    incumbent_candidate_id: str | None = None
    candidates: tuple[CandidateEnvelope, ...] = ()
    members: tuple[FrontierMember, ...] = ()
    selection_policy: str = "incumbent_only"
    max_live_members: int = 1
    updated_at: str = ""
    idea_summary: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "incumbent_candidate_id": self.incumbent_candidate_id,
            "candidates": [candidate.to_json() for candidate in self.candidates],
            "members": [member.to_json() for member in self.members],
            "selection_policy": self.selection_policy,
            "max_live_members": self.max_live_members,
            "updated_at": self.updated_at,
            "idea_summary": dict(self.idea_summary),
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "FrontierState":
        return cls(
            schema_version=int(raw.get("schema_version", FRONTIER_SCHEMA_VERSION) or FRONTIER_SCHEMA_VERSION),
            incumbent_candidate_id=(
                str(raw.get("incumbent_candidate_id")).strip()
                if raw.get("incumbent_candidate_id") not in {None, ""}
                else None
            ),
            candidates=tuple(
                CandidateEnvelope.from_json(item)
                for item in raw.get("candidates", [])
                if isinstance(item, dict)
            ),
            members=tuple(
                FrontierMember.from_json(item)
                for item in raw.get("members", [])
                if isinstance(item, dict)
            ),
            selection_policy=str(raw.get("selection_policy", "incumbent_only")).strip() or "incumbent_only",
            max_live_members=max(1, int(raw.get("max_live_members", 1) or 1)),
            updated_at=str(raw.get("updated_at", "")).strip(),
            idea_summary=dict(raw.get("idea_summary", {})),
        )


def empty_frontier_state(*, selection_policy: str = "incumbent_only", max_live_members: int = 1) -> FrontierState:
    return FrontierState(
        selection_policy=selection_policy,
        max_live_members=max(1, int(max_live_members)),
        updated_at=iso_timestamp_now(),
        idea_summary={},
    )


def load_frontier(paths: Any) -> FrontierState | None:
    if not paths.frontier_path.exists():
        return None
    payload = read_json(paths.frontier_path)
    if "schema_version" in payload and "candidates" in payload and "members" in payload:
        return FrontierState.from_json(payload)
    return None


def save_frontier(paths: Any, frontier: FrontierState) -> None:
    write_json(paths.frontier_path, frontier.to_json())


def frontier_from_legacy(paths: Any, *, state: Any | None = None) -> FrontierState:
    idea_summary: dict[str, Any] = {}
    if paths.frontier_path.exists():
        try:
            payload = read_json(paths.frontier_path)
            if "schema_version" not in payload:
                idea_summary = dict(payload)
        except Exception:
            idea_summary = {}
    incumbent_candidate_id = None
    candidates: tuple[CandidateEnvelope, ...] = ()
    members: tuple[FrontierMember, ...] = ()
    if state is not None and getattr(state, "yang_kept_passed", None) is not None:
        candidate_id = str(getattr(state, "yang_kept_candidate_id", "") or "legacy-incumbent").strip() or "legacy-incumbent"
        incumbent_candidate_id = candidate_id
        envelope = candidate_envelope_from_paths(
            paths,
            candidate_id=candidate_id,
            parent_ids=(),
            law_source_hash=str(getattr(state, "yang_kept_source_hash", "") or ""),
            eval_refs=[_relative(paths.results_path)] if paths.results_path.exists() else [],
            status="active",
            created_at=iso_timestamp_now(),
            updated_at=iso_timestamp_now(),
        )
        member = frontier_member_from_record(
            {
                "passed": bool(getattr(state, "yang_kept_passed", False)),
                "score": getattr(state, "yang_kept_score", {"summary": {}}) or {"summary": {}},
            },
            candidate_id=candidate_id,
            last_eval_ref=_relative(paths.results_path) if paths.results_path.exists() else None,
        )
        candidates = (envelope,)
        members = (member,)
    return FrontierState(
        incumbent_candidate_id=incumbent_candidate_id,
        candidates=candidates,
        members=members,
        selection_policy="incumbent_only",
        max_live_members=1,
        updated_at=iso_timestamp_now(),
        idea_summary=idea_summary,
    )


def candidate_envelope_from_paths(
    paths: Any,
    *,
    candidate_id: str,
    parent_ids: list[str] | tuple[str, ...],
    law_source_hash: str,
    eval_refs: list[str] | tuple[str, ...],
    status: str = "active",
    branch_id: str = "incumbent",
    created_at: str | None = None,
    updated_at: str | None = None,
) -> CandidateEnvelope:
    timestamp = created_at or iso_timestamp_now()
    updated = updated_at or timestamp
    artifact_refs = {
        "yang": _relative(paths.yang_path),
        "yin": _relative(paths.yin_path),
        "results": _relative(paths.results_path),
        "workspace": _relative(paths.workspace_path),
    }
    if getattr(paths.config, "problem_kind", "program_search") == "mechanism_search":
        artifact_refs.update({
            "candidate": _relative(paths.yang_candidate_path),
            "witness": _relative(paths.yang_witness_path),
            "derivation": _relative(paths.yang_derivation_path),
        })
    return CandidateEnvelope(
        candidate_id=candidate_id,
        branch_id=branch_id,
        parent_ids=tuple(parent_ids),
        artifact_refs=artifact_refs,
        law_ref={"source_hash": law_source_hash},
        eval_refs=tuple(eval_refs),
        cost_ledger_ref=None,
        created_at=timestamp,
        last_updated_at=updated,
        status=status,
    )


def frontier_member_from_record(
    record: dict[str, Any],
    *,
    candidate_id: str,
    last_eval_ref: str | None = None,
    current_tier: str = "tier1",
    cost_spent: float = 0.0,
) -> FrontierMember:
    summary = dict(record.get("score", {}).get("summary", {})) if isinstance(record.get("score"), dict) else {}
    simplicity = float(summary.get("simplicity", 0.0) or 0.0)
    robustness = float(summary.get("robustness", 0.0) or 0.0)
    return FrontierMember(
        candidate_id=candidate_id,
        status="active" if bool(record.get("passed")) else "candidate",
        current_tier=current_tier,
        last_eval_ref=last_eval_ref,
        novelty=0.0,
        simplicity=simplicity,
        robustness=robustness,
        cost_spent=cost_spent,
    )


def upsert_incumbent(
    frontier: FrontierState,
    *,
    envelope: CandidateEnvelope,
    member: FrontierMember,
) -> FrontierState:
    kept_candidates = [candidate for candidate in frontier.candidates if candidate.candidate_id != envelope.candidate_id]
    kept_members = [item for item in frontier.members if item.candidate_id != member.candidate_id]
    kept_candidates.append(envelope)
    kept_members.append(member)
    return FrontierState(
        schema_version=FRONTIER_SCHEMA_VERSION,
        incumbent_candidate_id=envelope.candidate_id,
        candidates=tuple(kept_candidates[-1:]),
        members=tuple(kept_members[-1:]),
        selection_policy=frontier.selection_policy or "incumbent_only",
        max_live_members=max(1, frontier.max_live_members),
        updated_at=iso_timestamp_now(),
        idea_summary=dict(frontier.idea_summary),
    )


def update_frontier_idea_summary(paths: Any, summary: dict[str, Any]) -> FrontierState:
    frontier = load_frontier(paths)
    if frontier is None:
        frontier = frontier_from_legacy(paths)
    updated = FrontierState(
        schema_version=frontier.schema_version,
        incumbent_candidate_id=frontier.incumbent_candidate_id,
        candidates=frontier.candidates,
        members=frontier.members,
        selection_policy=frontier.selection_policy,
        max_live_members=frontier.max_live_members,
        updated_at=iso_timestamp_now(),
        idea_summary=dict(summary),
    )
    save_frontier(paths, updated)
    return updated
