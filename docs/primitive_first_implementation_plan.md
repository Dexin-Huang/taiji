# Primitive-First Implementation Plan

This document turns the redesign into a migration plan against the current runtime.

It assumes the revised kernel from [cost_aware_ecology_redesign.md](D:/Projects/taiji/docs/cost_aware_ecology_redesign.md):

- `state`
- `variation`
- `evaluation`
- `selection`
- `archive_transfer`
- `allocation`

## Goal

Make five currently implicit concerns explicit in the runtime:

- candidate provenance
- frontier
- selection
- archive transfer
- allocation

while preserving:

- mechanical evaluation
- strict ownership
- typed problem surfaces
- frozen-law inner loop
- conservative default behavior

## Non-Goals

This plan intentionally does not start with:

- wide parallel candidate swarms
- rich role ontologies
- homeostatic Yin in full generality
- broad unit format rewrites
- prompt proliferation

Those can come later as policies.

## Current Runtime Map

The existing runtime already contains partial versions of the target kernel.

### State

Present via:

- [`taiji/runtime/config.py`](D:/Projects/taiji/taiji/runtime/config.py)
- [`taiji/runtime/cycle.py`](D:/Projects/taiji/taiji/runtime/cycle.py)
- run-local artifact copies

Missing:

- explicit candidate envelope
- explicit provenance
- explicit resource ledger

### Variation

Present via:

- owned-file edits
- repeated `run_cycle` trials

Missing:

- explicit mutation records

### Evaluation

Already strong via:

- [`taiji/runtime/law.py`](D:/Projects/taiji/taiji/runtime/law.py)
- [`taiji/runtime/cycle.py`](D:/Projects/taiji/taiji/runtime/cycle.py)

Missing:

- fidelity metadata
- provisional vs decisive distinction
- evaluation caching hooks

### Selection

Present but narrow via:

- [`taiji/runtime/loop.py`](D:/Projects/taiji/taiji/runtime/loop.py)

Missing:

- explicit admit / continue / retire semantics
- frontier-driven selection

### Archive Transfer

Present weakly via:

- notebooks
- `workspace/`
- histories
- current working artifacts

Missing:

- typed shared archive
- publish/adopt flow
- auditability

### Allocation

Present weakly via:

- turn caps
- wall-clock caps
- cycle-call caps

Missing:

- explicit budget state
- tier gating
- continuation pressure

## Recommended Runtime Objects

### 1. `CandidateEnvelope`

Represents one branch-local candidate with provenance.

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

This is the quiet step zero that should precede richer frontier behavior.

### 2. `FrontierMember`

Represents one live candidate under selection.

Minimum fields:

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

### 3. `FrontierState`

Represents the maintained live set.

Minimum fields:

```text
members[]
selection_policy
max_live_members
updated_at
```

### 4. `ArchiveRecord`

Represents one typed published artifact available for reuse.

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

### 5. `AllocationState`

Represents budget and gating state.

Minimum fields:

```text
iteration
budget_profile
expensive_budget_remaining
frontier_cap
tier_gate
stopping_state
created_at
```

## Recommended File Layout

Keep the module additions minimal.

### New Modules

Recommended:

- `taiji/runtime/frontier.py`
- `taiji/runtime/archive.py`
- `taiji/runtime/allocation.py`

These correspond directly to the missing runtime primitives.

### Existing Modules To Change

- [`taiji/runtime/loop.py`](D:/Projects/taiji/taiji/runtime/loop.py)
- [`taiji/runtime/ideas.py`](D:/Projects/taiji/taiji/runtime/ideas.py)
- [`taiji/runtime/prompts.py`](D:/Projects/taiji/taiji/runtime/prompts.py)
- [`taiji/runtime/cycle.py`](D:/Projects/taiji/taiji/runtime/cycle.py)
- [`taiji/runtime/config.py`](D:/Projects/taiji/taiji/runtime/config.py)
- [`taiji/runtime/bootstrap.py`](D:/Projects/taiji/taiji/runtime/bootstrap.py) only if defaults need scaffolding
- [`taiji/runtime/smoke.py`](D:/Projects/taiji/taiji/runtime/smoke.py)

## Phase 0: Candidate Envelope and Provenance

This should come first.

### Purpose

Stop treating branch state as anonymous working copies.

### Concrete Changes

Add a candidate envelope model that records:

- stable ids
- lineage
- artifact refs
- evaluation refs
- resource ledger

This can live in `frontier.py` initially if we want to keep module count low.

### Compatibility Rule

The default runtime may still behave like one working copy, but every evaluated candidate should already have a stable envelope.

## Phase 1: Frontier As First-Class State

### Purpose

Turn `frontier.json` from a report into an authoritative runtime object.

### Concrete Changes

#### `taiji/runtime/frontier.py`

Add:

- `FrontierMember`
- `FrontierState`
- `load_frontier(paths)`
- `save_frontier(paths, frontier)`
- `frontier_from_legacy(paths)`

#### `taiji/runtime/ideas.py`

Keep:

- idea recording
- summaries

Remove responsibility for:

- active frontier semantics

`ideas.py` should remain archival.

`frontier.py` should become operational.

### Compatibility Rule

Default policy:

```text
selection_policy = incumbent_only
max_live_members = 1
```

So Phase 1 reproduces current behavior closely.

## Phase 2: Archive Transfer

This fixes weak structural inheritance before widening selection.

### Purpose

Allow useful structure from failed branches to survive mechanically.

### Concrete Changes

#### `taiji/runtime/archive.py`

Add:

- `ArchiveRecord`
- `publish_artifact(...)`
- `adopt_artifact(...)`
- `load_archive(paths)`
- `save_archive(paths, archive)`

#### Shared Archive Root

Recommended path:

```text
runs/<unit>/<run_id>/shared/
```

Suggested subdirs:

- `shared/modules/`
- `shared/witness_fragments/`
- `shared/counterexamples/`

### Initial Policy

Support one artifact type first:

- reusable Python module

Publish criteria:

- parses/imports
- branch-independent enough
- explicitly marked for publish

Adoption should always happen through explicit references, not implicit leakage.

## Phase 3: Selection Generalization

### Purpose

Make selection explicit as:

- admit
- continue
- retire

### Concrete Changes

#### `taiji/runtime/frontier.py`

Add:

- `admit_candidate(...)`
- `continue_candidates(...)`
- `retire_candidates(...)`
- `select_members(...)`

Initial policies:

- `incumbent_only`
- `top_k`

Optional later:

- `top_k_plus_novelty`
- `pareto`

#### `taiji/runtime/loop.py`

Replace inline keep/discard with:

- construct candidate envelope
- evaluate
- ask selection to admit / continue / retire
- persist updated frontier

### Compatibility Rule

When:

- `selection_policy = incumbent_only`
- `max_live_members = 1`

runtime behavior should still approximate current Taiji.

## Phase 4: Evaluation Metadata and Tiers

### Purpose

Separate cheap filtering from decisive evaluation without blurring law semantics.

### Concrete Changes

#### `taiji/runtime/cycle.py`

Add evaluation record metadata:

- `tier`
- `evaluator_identity`
- `cost_hint`
- `provisional`

#### `taiji/runtime/allocation.py`

Add simple tier gates:

- `tier0`
- `tier1`
- `tier2`

Initial semantics:

- `tier0`: static/schema checks
- `tier1`: current default evaluation path
- `tier2`: reserved for richer checks later

### Important Rule

Low-tier results must never silently become final acceptance-law judgments.

## Phase 5: Allocation Hook

### Purpose

Make budget and gating explicit without turning allocation into a strategy engine.

### Concrete Changes

#### `taiji/runtime/allocation.py`

Add:

- `AllocationState`
- `load_allocation_state(paths)`
- `save_allocation_state(paths, state)`
- `allow_expensive_evaluation(...)`
- `frontier_capacity(...)`
- `stopping_state(...)`

### Initial Scope

Allocation owns only:

- budget accounting
- frontier caps
- tier gating
- stopping conditions

Not yet:

- homeostatic law reshaping
- broad prompt strategy
- rich adaptive policy

## Prompt Changes

Prompts should change less than the runtime at first.

### Keep

- current yin/yang identities
- current ownership rules
- typed candidate/witness framing

### Add

- candidate/branch id
- frontier summary
- shared archive summary
- evaluation tier summary

### Avoid

- baking named runtime roles into prompt families

Those can come later as policy bundles if useful.

## Config Changes

Add a small optional search section with safe defaults.

Suggested fields:

```toml
[search]
selection_policy = "incumbent_only"
max_live_members = 1
default_evaluation_tier = "tier1"
allow_archive_publish = false
max_expensive_evals_per_20_iterations = 0
```

These are policy controls, not task semantics.

## Migration Rules

Every existing unit and run should still load.

That means:

- missing frontier state reconstructs conservatively
- missing archive state defaults empty
- missing allocation state defaults conservative

### Default Post-Migration Behavior

Equivalent to current behavior:

- one incumbent
- one live branch
- no archive transfer
- current-style evaluation path

## Testing Plan

Add smoke coverage incrementally.

### New Smoke Checks

1. `frontier_legacy_compat`
   - missing frontier file reconstructs safely

2. `selection_incumbent_only`
   - new selection path reproduces current behavior

3. `selection_top_k`
   - frontier can retain more than one live member

4. `archive_publish_module`
   - a published module survives branch discard

5. `archive_reject_invalid`
   - invalid or branch-coupled modules are rejected

6. `evaluation_tier_defaults`
   - old units still run under default tier behavior

7. `allocation_budget_gate`
   - expensive evaluations are blocked when budget says no

## Risks

### Risk 1: Branch Explosion

Mitigation:

- keep `k` tiny at first
- use lightweight envelopes
- preserve incumbent-only compatibility

### Risk 2: Archive Pollution

Mitigation:

- support one artifact type first
- require explicit publish intent
- keep publish criteria strict

### Risk 3: Allocation Drift

Mitigation:

- keep allocation narrow
- do not let it absorb prompt strategy or law semantics

### Risk 4: Selection Blob

Mitigation:

- explicitly separate admit / continue / retire

## Recommended Order

1. candidate envelope / provenance
2. first-class frontier
3. archive transfer
4. selection generalization
5. evaluation metadata and tiers
6. allocation hook

Only after those settle:

- consider richer policies
- consider homeostatic Yin
- consider perturbation-family laws

## Recommended PR Breakdown

### PR 1: Candidate Envelope + Frontier State

- add candidate provenance
- add `frontier.py`
- migrate `frontier.json` from report to state
- preserve incumbent-only behavior

### PR 2: Archive Transfer

- add `archive.py`
- add shared published module root
- support explicit publish/adopt for modules only

### PR 3: Selection Generalization

- move keep/discard behind admit / continue / retire semantics
- support `top_k`
- add branch-local artifact roots

### PR 4: Evaluation Metadata + Allocation

- add evaluation metadata
- add `allocation.py`
- gate expensive evaluation mechanically

## Summary

The first important outcome is not "an ecology."

It is:

candidate provenance, frontier, selection, archive transfer, and allocation become explicit runtime primitives instead of scattered implicit behavior.

Once that exists, richer ecological behavior can be added through policy without bending the runtime around temporary prompt strategies.
