# Goal

Derive a closed-form mechanism for encoder stability in a streaming world
model with retained fast weights.

This unit is mechanism-first. The primary deliverable is not a PyTorch
training run. The primary deliverable is:

- `candidate.json`: the mechanism family and its structural commitments
- `witness.json`: the parameter regime and bound inputs
- `derivation.md`: the analytic argument that the inequalities hold
- `implementation.py`: an optional compiled reference implementation

The host evaluates the mechanism mechanically from the candidate and
witness. The target world is a rotating-Gaussian stream with fixed seed,
fixed latent dimension, and explicit drift/carryover inequalities.

The core question is:

Can a two-timescale encoder plus carried-over fast weights keep encoder
drift inside a nontrivial cosine band while still preserving cross-shift
adaptation?

The law should be satisfied by derivation, not by black-box empirical
search. Use the candidate, witness, and derivation artifacts to state the
mechanism, solve the inequalities, and only then compile a reference
implementation if helpful.
