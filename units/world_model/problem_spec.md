# Problem Spec

## Goal

Derive a mechanism for streaming world-model learning that keeps encoder
drift inside a nontrivial cosine band while preserving fast-weight
carryover across distribution shifts.

## Candidate Family

- `mechanism`: `ema_retained_fast_weights` or `two_timescale_latent_carryover`
- `encoder_rule`: `ema_target` or `lagged_teacher`
- `predictor_rule`: `linear_residual` or `low_rank_linear`
- `fast_weight_rule`: `retained_delta` or `retained_hebbian`
- `consolidation_rule`: `ema_consolidation` or `sleep_replay_ema`

Candidates must keep a shared latent space and must carry fast weights
across shift boundaries.

## Mechanical Checks

The host recomputes the following quantities from `candidate.json`,
`witness.json`, and `world.json`:

1. `anchor_cosine = 1 - H * delta / 2`
2. `tau_target = M * delta`
3. `transition_ratio = 1 + S * delta / (retention + adaptation_gain)`
4. `reduction_lower = 1 - exp(-W * adaptation_gain * retention) - D * delta`

The law then checks:

- `0.90 <= anchor_cosine <= 0.98`
- `|tau - tau_target| <= 0.01`
- `transition_ratio <= 1.25`
- `reduction_lower >= 0.22`
- `retention >= 0.80`
- `latent_rank / latent_dim >= 0.75`
- `component_count <= 5`

## Required Witness Fields

- `delta`
- `tau`
- `retention`
- `adaptation_gain`

## Counterexamples

- Freeze the encoder so drift vanishes
- Reset fast weights at each shift
- Inject noise to fake drift without useful carryover
- Add decorative modules that do not change the closed-form witness
