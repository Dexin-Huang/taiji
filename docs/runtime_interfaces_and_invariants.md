# Runtime Interfaces and Invariants

This note turns the primitive-first redesign into concrete runtime interfaces and invariants.

It is meant to answer:

- what are the actual runtime objects?
- what must always remain true?

Related docs:

- [cost_aware_ecology_redesign.md](D:/Projects/taiji/docs/cost_aware_ecology_redesign.md)
- [primitive_first_implementation_plan.md](D:/Projects/taiji/docs/primitive_first_implementation_plan.md)

## Interface 1: Candidate Envelope

Every evaluated branch should have a stable candidate envelope.

Minimum fields:

```text
candidate_id
branch_id
parent_ids
artifact_refs
law_ref
eval_refs
cost_ledger_ref
created_at
last_updated_at
status
```

Required distinction:

- branch-local artifacts
- shared adopted artifacts

The runtime should stop acting on anonymous working copies once this exists.

## Interface 2: Evaluation Record

Every evaluation should produce a stable record.

Minimum fields:

```text
evaluation_id
candidate_id
law_ref
tier
evaluator_identity
passed
scorecard
cost
provisional
created_at
```

Important:

- low-tier evaluations are allowed
- low-tier evaluations must be explicitly provisional
- only decisive evaluation may determine final law acceptance

## Interface 3: Frontier

The frontier is the maintained set of candidates under selection.

Minimum fields:

```text
frontier_id
members[]
selection_policy
max_live_members
updated_at
```

Each frontier member should minimally expose:

```text
candidate_id
status
current_tier
last_eval_ref
novelty
simplicity
robustness
cost_spent
```

## Interface 4: Archive Record

Reusable structure should move through a typed archive.

Minimum fields:

```text
archive_id
artifact_type
source_candidate_id
source_path
shared_path
compatibility
evidence
published_at
```

Adoption should happen by explicit reference, not implicit branch leakage.

## Interface 5: Selection Decision

Selection should be recorded explicitly and decomposed into:

- admit
- continue
- retire

Minimum fields:

```text
decision_id
candidate_id
decision_kind
reason
policy
budget_context
created_at
```

## Interface 6: Allocation Record

Allocation governs spend and gating.

Minimum fields:

```text
allocation_id
iteration
budget_profile
expensive_budget_remaining
frontier_cap
tier_gate
stopping_state
created_at
```

## Core Invariants

### Invariant 1: Host Mechanical

The runtime may:

- load
- copy
- evaluate
- compare
- publish
- adopt
- gate

The runtime may not invent task semantics.

### Invariant 2: Ownership Remains Strict

Yin and Yang ownership boundaries remain mechanically enforced.

Archive transfer must not become a hidden side channel around ownership.

### Invariant 3: Provenance Is Required

Every candidate, evaluation, and archive record must have stable provenance.

No anonymous state should affect selection.

### Invariant 4: Low Fidelity Is Never Final Law

Cheap or low-tier checks may filter or prioritize.

They may not silently become final pass/fail under the law.

### Invariant 5: Archive Transfer Is Typed and Auditable

Published artifacts must carry:

- type
- source
- compatibility
- evidence

Branches should adopt shared artifacts by explicit reference.

### Invariant 6: Selection Must Be Explicit

Every admit, continue, and retire action should have a recorded reason.

### Invariant 7: Allocation Only Governs Resources

Allocation may govern:

- cost
- gating
- continuation pressure
- stopping

Allocation should not become a disguised strategy engine.

### Invariant 8: Default Behavior Remains Conservative

Without explicit policy changes, the runtime should remain close to current Taiji behavior:

- one incumbent
- one live branch
- no archive transfer
- current-style evaluation path

## Design Consequence

Once these interfaces and invariants exist, richer behaviors become policies rather than new runtime ontology.

Examples:

- top-k frontier
- novelty preservation
- cheap-vs-expensive model allocation
- branch rescue
- homeostatic pressure tuning

None of those should require changing the kernel concepts again.
