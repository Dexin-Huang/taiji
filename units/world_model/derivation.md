# Derivation

## bounded-drift

Use the anchor drift approximation

`anchor_cosine ~= 1 - H * delta / 2`

with `H = anchor_probe_horizon_steps`.

## tau-consistency

Tie the EMA rate to the drift budget with

`tau_target = ema_tau_multiplier * delta`.

The seed witness is intentionally loose here: `tau = 0.02` while
`tau_target = 6 * 0.008 = 0.048`.

## transition-ratio

For retained fast weights, bound the post-shift cold start by

`transition_ratio <= 1 + shift_sensitivity * delta / (retention + adaptation_gain)`.

Higher retention and faster adaptation lower the ratio.

## reduction-bound

Use the closed-form lower bound

`reduction >= 1 - exp(-W * adaptation_gain * retention) - D * delta`

with `W = adaptation_window_steps` and `D = drift_penalty_scale`.

The seed witness keeps the right family but does not yet satisfy the
required reduction margin.
