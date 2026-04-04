# Primitive-First Cost-Aware Redesign

This note updates the redesign after external feedback.

The direction stays the same:

- simplify the runtime
- keep the host mechanical
- move behavior out of runtime ontology and into policy

The main correction is that the kernel should be sharpened before it is frozen.

## Thesis

Taiji should not evolve into a runtime full of named characters like:

- scout
- builder
- rescuer
- scheduler

Those may be useful prompt or policy bundles later, but they should not define the core runtime model.

The runtime should first become a small adaptive kernel with explicit primitives.

## The Revised Primitive Set

The kernel should be framed as:

1. `state`
2. `variation`
3. `evaluation`
4. `selection`
5. `archive_transfer`
6. `allocation`

This is close to the earlier six, but two names are sharper:

- `archive_transfer` instead of vague `inheritance`
- `allocation` instead of broad `control`

## Why These Primitives

### 1. State

State is the thing under selection.

For Taiji, it should not mean only "the current candidate files."

It should explicitly include:

- branch-local state
- shared adopted state
- provenance
- artifact references
- evaluation references
- resource references

That means every candidate needs a real envelope, not just a working directory.

### 2. Variation

Variation is local change:

```text
mutate(state, context) -> state'
```

The runtime should support variation without caring whether the mutation came from:

- a cheap model
- an expensive model
- a heuristic operator
- a human-written rewrite

Those are policy choices, not kernel concepts.

### 3. Evaluation

Evaluation stays one of Taiji's strongest ideas:

```text
evaluate(candidate_state, law_state) -> evaluation_record
```

But the record should be richer than a bare pass/fail plus score.

It should carry:

- pass/fail
- scorecard
- fidelity tier
- evaluator identity
- cost
- provisional vs decisive status

Important invariant:

Low-tier evaluation may filter or prioritize, but it must not silently become final law acceptance.

### 4. Selection

Selection is not one opaque decision.

It is three decisions:

- admit
- continue
- retire

That is the right way to think about it.

Today Taiji mostly does:

- keep one incumbent
- discard everything else

That is a policy. It should not be the kernel definition.

### 5. Archive / Transfer

The old word `inheritance` was pointing at the right concern, but the better mechanism is:

- publish reusable structure into a typed shared archive
- adopt that structure into another branch by explicit reference

This is cleaner than vague inheritance language.

It preserves:

- provenance
- auditability
- compatibility checking
- strict ownership in spirit as well as syntax

It also avoids treating whole branches as inherited worlds. Branches should donate typed artifacts, not hidden context.

### 6. Allocation

The old word `control` was too broad.

The narrow primitive we actually need is:

- budget accounting
- frontier caps
- tier gating
- continuation quotas
- stopping conditions

That is an allocation or governance primitive, not a vague strategy engine.

Later homeostatic behavior can build on top of this, but the kernel should start narrow.

## What This Means

The runtime kernel should not be:

- roles
- search personalities
- social metaphor

It should be:

- typed states
- local variation
- explicit evaluation
- explicit admit/continue/retire
- typed archive-mediated reuse
- explicit resource allocation

That is a cleaner and more stable architecture.

## Three Layers

The runtime should still be understood in three layers.

### Layer 1: Kernel

Only:

- state
- variation
- evaluation
- selection
- archive_transfer
- allocation

### Layer 2: Policies

Policies choose how the kernel behaves.

Examples:

- frontier size
- novelty weighting
- simplicity weighting
- cheap vs expensive model mix
- evaluation tier ladder
- archive publication friction
- branch retirement thresholds

### Layer 3: Unit Formalization

Units define task-specific problem shape:

- artifact schema
- witness schema
- verifier
- perturbation family
- allowed mutation surface

The runtime should remain stable while units vary.

## Cost Story

The cost answer should remain:

- cheap variation
- sparse expensive certification

not:

- many full expensive candidates in parallel

The right objective is:

```text
expected useful improvement per unit spend
```

That means:

- expensive model budget should be reserved for hard critique, law design, rescue, and final synthesis
- cheap model budget should do most local mutation and low-tier exploration

This stays a policy choice over the same kernel.

## Frontier

The frontier should become a real runtime object, not just a report.

But the frontier should be understood as data structure, not ontology.

It is:

- the maintained set of candidate envelopes under selection

It is not:

- a social metaphor
- a runtime "population system" with lots of bespoke concepts

The frontier exists so selection has a clear object to act on.

## Archive Transfer

Archive transfer is the right answer to weak structural inheritance.

The model should be:

1. publish a typed artifact into a shared archive
2. adopt it into another branch through an explicit reference

That gives:

- reusable structure from failed branches
- mechanical traceability
- compatibility checking
- less prompt-policy smuggling

The first implementation can still use "promotion" as the publish mechanism, but the broader model should be archive-mediated transfer.

## Allocation

Allocation should initially stay narrow.

It should govern:

- spend
- gating
- frontier pressure
- stopping

It should not initially govern:

- prompt semantics
- rich law strategy
- broad adaptive policy

That prevents allocation from becoming a junk drawer.

## What Is Strong In Current Taiji

The current runtime already has strong foundations worth preserving:

- mechanical host
- explicit/public evaluation
- strict ownership
- frozen-law inner loop
- typed candidate surfaces
- conservative default behavior

The redesign should strengthen these invariants, not relax them.

## Main Architectural Risk

The redesign fails if it reintroduces complexity through runtime naming instead of runtime primitives.

It also fails if:

- low-tier evaluation becomes de facto final law
- archive transfer becomes an unverifiable merge channel
- allocation becomes a disguised scheduler/strategy layer
- provenance is not first-class

Those are the places where explicit invariants matter most.

## Summary

The direction is still right.

But the kernel should now be stated more sharply:

- `state` with provenance and local/shared distinction
- `variation`
- `evaluation` with fidelity metadata
- `selection` as admit / continue / retire
- `archive_transfer`
- `allocation`

That is a better primitive-first runtime than the earlier wording, while keeping the same basic simplification thesis.
