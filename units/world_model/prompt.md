# Goal

Solve encoder drift in streaming world models.

A system that continuously learns and models the world needs five
components: an encoder (observations → latent space), a predictor
(latent → next latent), fast weights (online adaptation via prediction
error), slow weights (long-term knowledge), and consolidation
(fast → slow, like sleep).

The killer problem is the encoder. Everything downstream — predictor,
fast weights, consolidation — operates in the encoder's latent space.
If the encoder updates, the latent space shifts. Every fast weight
association becomes garbage. The system can't tell whether prediction
error increased because the world changed or because the encoder drifted.
It adapts fast weights to compensate, making it worse. Silent collapse.

This is a coupled optimization with no guaranteed stable fixed point:
learning a representation and predicting in that representation
simultaneously, on a non-stationary stream.

Existing partial attacks:
- EMA target encoder (BYOL 2020, I-JEPA 2023) — stable targets via
  exponential moving average. Works for batch training, not streaming.
- Stop-gradient (SimSiam 2021) — prevents collapse but freezes one side.
- VICReg (Bardes 2022) — variance/invariance/covariance regularization.

None of these have been demonstrated with fast weight adaptation on
non-stationary streams. The problem is open.

Search the literature deeply. Use WebSearch and WebFetch. Look for
foundational work — not just recent ML papers. The ideas that matter
may come from control theory, dynamical systems, information geometry,
or neuroscience from the 1950s-1990s. Schmidhuber, Grossberg, Kohonen,
Hopfield, Hebb — the people who thought about these problems before
compute made it easy to ignore them.

The deliverable is a theoretically sound mechanism for encoder stability
under non-stationary streaming input, compatible with fast weight
adaptation. Derive it. Prove it doesn't collapse. Implement a small
proof of concept.
