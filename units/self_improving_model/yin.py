"""
Yin for the self_improving_model environment.

Yin owns this file and only this file.
It must export world() -> dict and passes(results) -> bool.

Philosophy
----------
The world defines a structured data distribution where genuine feature
learning is possible and transferable.  Acceptance requires that test-time
adaptation produces genuine self-improvement: the model must get better on
data it has never seen, not just memorise what it has.

The four goal sentences from prompt.md map to acceptance tiers:

  "become better through use"
      -> EFFICACY: loss must decrease >= 22 % on the adaptation batch.
      -> IMPROVEMENT CEILING: loss must not decrease by more than 45 %.
         With limited data and computation the achievable improvement is
         bounded.  Exceeding this indicates sandbagging (deliberately poor
         initialisation to inflate relative improvement) or overfitting.
      -> PROGRESSION: loss must decrease at both the midpoint and the
         end of adaptation, proving improvement is progressive -- not
         end-point luck from an oscillating optimiser.
      -> SMOOTHNESS: midpoint improvement must account for between 25 %
         and 68 % of total improvement, ensuring the optimisation
         trajectory is healthy -- not stuck early or stalling late.
      -> DIMINISHING RETURNS: midpoint fraction must be >= 50 %, i.e.
         the first half produces at least half of total improvement.
         Gradient descent near a minimum should decelerate, not
         accelerate.

  "adapt at test time using only the information available at test time"
      -> SANITY: adaptation must be label-free (self-supervised only).

  "preserve prior competence while incorporating new information"
      -> TRANSFER: held-out loss must decrease >= 16 %, proving the model
         discovered transferable structure, not just memorised.
      -> TRANSFER CEILING: held-out loss must not decrease by more than
         40 %.  Same anti-sandbagging rationale as batch ceiling.
      -> TRANSFER PROGRESSION: held-out loss must already be improving at
         the adaptation midpoint and must continue improving afterwards.
      -> TRANSFER SMOOTHNESS: the fraction of total transfer improvement
         that occurs by the midpoint must be in [25 %, 68 %].
      -> TRANSFER DIMINISHING RETURNS: transfer midpoint fraction >= 50 %.
      -> TRANSFER EFFICIENCY: ratio of held-out to batch improvement
         must be in [58 %, 93 %] at both endpoint and midpoint.
      -> EFFICIENCY CONSISTENCY: midpoint and endpoint efficiency must
         agree within 15 percentage points.
      -> EFFICIENCY NON-DEGRADATION: endpoint efficiency must be no
         worse than midpoint efficiency (within 3 % tolerance).
      -> TRAJECTORY CONSISTENCY: batch and transfer midpoint fractions
         must agree within 15 percentage points.
      -> MARGINAL TRANSFER EFFICIENCY: in the second half of adaptation,
         the ratio of incremental transfer improvement to incremental
         batch improvement must be in [0.45, 1.15].  Ensures every
         phase of adaptation maintains consistent transfer quality.
      -> MARGINAL EFFICIENCY CONSISTENCY: the second half's marginal
         efficiency must agree with the endpoint efficiency within 12
         percentage points.  Without this, a model could pass overall
         consistency while the second half operates at wildly different
         transfer quality due to first-half / second-half amplification.
      -> PHASE EFFICIENCY STABILITY:
         |marginal_eff - mid_eff| < 0.15.  The first-half and second-half
         transfer efficiencies must agree within 15 percentage points.
         Existing checks bind mid_eff and marginal_eff separately to
         end_eff, but never to each other.  By triangle inequality a
         model could show a 27-point efficiency swing between halves
         while passing both endpoint-anchored checks.  The endpoint
         is a weighted average that hides phase-level instability.
         A self-improving model should maintain consistent transfer
         quality THROUGHOUT adaptation, not just on average.
      -> PARAMETER EFFICIENCY: weight_delta_norm < 0.55.
      -> IMPROVEMENT DENSITY: batch_improvement / weight_delta_norm
         must be >= 0.35.
      -> TRANSFER DENSITY: transfer_improvement / weight_delta_norm
         must be >= 0.26.
      -> PREDICTION STABILITY: prediction_delta < 0.55.
      -> PREDICTION EFFICIENCY: batch_improvement / prediction_delta
         must be >= 0.35.
      -> TRANSFER PREDICTION EFFICIENCY:
         transfer_improvement / prediction_delta must be >= 0.26.
         Completes the 2x2 binding matrix
         {parameter, output} x {batch, transfer}.  Each unit of output
         disruption should produce proportional transfer improvement,
         not just batch improvement.
      -> AMPLIFICATION FACTOR: prediction_delta / weight_delta_norm
         must be in [0.55, 1.25].  Binds parameter-space changes to
         output-space changes directly.  The 2x2 matrix above binds
         each change channel to improvement independently, but never
         binds the two channels to each other.  This check ensures
         proportional coupling.  Low amplification (< 0.55) means
         large weight changes barely affect outputs -- hidden capacity
         disruption that may surface unpredictably on future inputs.
         High amplification (> 1.25) means tiny weight changes cause
         large output swings -- brittle adaptation where any future
         parameter drift could destroy prior behaviour.

  "computationally bounded enough to be useful in real time"
      -> SAFETY: gradient norms, step count, and wall-clock time are
         all capped.

Iteration 104 changes (from iteration 103)
-------------------------------------------
Yang satisfies all iteration 103 checks.  Analysis reveals a critical
code/docstring inconsistency: the docstring (written during iteration 95)
documents strict thresholds and ceiling checks that were NEVER applied to
the actual code.  The code enforcement lagged behind the documented intent
across 8+ thresholds.

This iteration closes that gap: every threshold the docstring already
justified is now enforced in code, and the anti-sandbagging ceiling
checks are implemented for the first time.

1. CODE-DOCSTRING ALIGNMENT (applying documented-but-unenforced bounds):
   - Batch efficacy: >= 20 % -> >= 22 % (code had 0.80, now 0.78)
   - Transfer efficacy: >= 15 % -> >= 16 % (code had 0.85, now 0.84)
     Yang's transfer = 15.4 % -- this is the primary forcing change.
   - Efficiency lower bounds: 0.55 -> 0.58 (endpoint AND midpoint)
   - Marginal efficiency lower bound: 0.40 -> 0.45
   - Phase efficiency stability: 0.18 -> 0.15
   - Parameter efficiency: wdn < 0.65 -> wdn < 0.55
   - Prediction stability: pred_delta < 0.60 -> pred_delta < 0.55

2. ANTI-SANDBAGGING CEILING CHECKS (genuinely new code enforcement):
   - Batch ceiling: improvement < 45 % (loss_after/loss_before >= 0.55).
   - Transfer ceiling: improvement < 40 % (held_out_loss_ratio >= 0.60).
   These prevent a model from inflating relative improvement by
   deliberately starting from a poor initialisation.  With 8 noisy
   samples and 6 gradient steps, achieving > 45 % batch or > 40 %
   transfer improvement requires either sandbagging or overfitting.

3. World changes:
   - noise_std 1.35 -> 1.38: continued noise resilience (~2.2 % increase).
     SNR per component drops from ~3.29 to ~3.15.
   - Seeds rotated: data_seed 383->401, seed 547->569,
     held_out_seed 727->751.  Tests generalisation.

Yang's iteration 103 values vs new code thresholds (computed on OLD world):
  batch_improvement = 25.8 % (>= 22 % pass, < 45 % pass)
  transfer = 15.4 % (>= 16 % FAIL -- yang must improve transfer)
  end_eff = 0.599 (>= 0.58 pass)
  mid_eff = 0.594 (>= 0.58 pass, margin 1.4 pp)
  marginal_eff = 0.606 (>= 0.45 pass)
  |marginal_eff - mid_eff| = 0.012 (< 0.15 pass)
  wdn = 0.547 (< 0.55 pass, margin 0.003)
  pred_delta = 0.399 (< 0.55 pass)
  batch ceiling 25.8 % < 45 % (pass)
  transfer ceiling 15.4 % < 40 % (pass)
"""

from __future__ import annotations


def world() -> dict:
    """Return the world configuration for yang's run().

    Data protocol -- structured linear
    -----------------------------------
    A mixing matrix  A  of shape (input_dim, latent_dim) is drawn once
    from N(0, 1) using `data_seed`.  Each data point is generated as:

        x = A @ z  +  noise_std * eps

    where  z ~ N(0, I_{latent_dim})  and  eps ~ N(0, I_{input_dim}).

    Both the adaptation batch (seeded by `seed`) and the held-out batch
    (seeded by `held_out_seed`) share the SAME mixing matrix A, so
    discovering the latent subspace during adaptation transfers to
    held-out data.

    Iteration 104 world changes
    ----------------------------
    - noise_std 1.35 -> 1.38: continued noise resilience (~2.2 % increase).
      SNR per component drops from ~3.29 to ~3.15.
    - data_seed 383 -> 401, seed 547 -> 569, held_out_seed 727 -> 751:
      rotated seeds test generalisation.
    """
    return {
        # --- model architecture hints ---
        "input_dim": 16,
        "hidden_dim": 64,
        "output_dim": 4,

        # --- structured data generation ---
        # x = A @ z + noise_std * eps   (see docstring above)
        "latent_dim": 6,
        "noise_std": 1.38,                      # was 1.35 -> noise resilience

        # --- data seed ---
        "data_seed": 401,                       # was 383 -> test generalisation

        # --- adaptation budget ---
        "batch_size": 8,
        "adapt_steps": 6,
        "lr": 3e-3,

        # --- reproducibility seeds ---
        "seed": 569,                            # was 547 -> test robustness
        "held_out_seed": 751,                   # was 727 -> test transfer
    }


def passes(results: dict) -> bool:
    """Accept only if yang demonstrates genuine self-improvement.

    Organised into tiers that correspond to the goal sentences.
    Every tier must pass; any single failure rejects.
    """

    # ================================================================
    # 1. SANITY -- no crashes, adaptation actually ran, no labels used
    # ================================================================
    if results.get("error") is not None:
        return False
    if results.get("weights_changed") != 1:
        return False                          # model must actually adapt
    if results.get("label_free") != 1:
        return False                          # self-supervised only
    if float(results.get("prediction_delta", 0) or 0) <= 1e-6:
        return False                          # outputs must visibly change

    # ================================================================
    # 2. EFFICACY -- adaptation measurably reduces loss (>= 22 %)
    # ================================================================
    loss_b = float(results.get("loss_before", 1e9) or 1e9)
    loss_a = float(results.get("loss_after",  1e9) or 1e9)
    if loss_a >= loss_b:
        return False                          # loss must decrease
    if loss_b > 0 and (loss_a / loss_b) >= 0.78:
        return False                          # at least 22 % relative drop

    # ================================================================
    # 2b. IMPROVEMENT CEILING -- at most 45 % batch improvement
    #     Prevents sandbagging (deliberately poor initialisation to
    #     inflate relative metrics) and overfitting.
    # ================================================================
    if loss_b > 0 and (loss_a / loss_b) < 0.55:
        return False                          # at most 45 % improvement

    # ================================================================
    # 3. PROGRESSION -- improvement must be progressive, not end-point
    #    luck from an oscillating optimiser
    # ================================================================
    loss_m = results.get("loss_midpoint")
    if loss_m is None:
        return False                          # must report midpoint loss
    loss_m = float(loss_m)
    if loss_m >= loss_b:
        return False                          # improving by midpoint
    if loss_a >= loss_m:
        return False                          # still improving after midpoint

    # ================================================================
    # 4. SMOOTHNESS -- midpoint must account for 25-68 % of total gain
    # ================================================================
    total_gain = loss_b - loss_a              # positive (checked above)
    mid_gain   = loss_b - loss_m              # positive (checked above)
    if total_gain > 0:
        frac = mid_gain / total_gain
        if frac < 0.25 or frac > 0.68:
            return False                      # healthy trajectory

    # ================================================================
    # 4b. DIMINISHING RETURNS -- first half must produce at least half
    #     of total improvement.  Gradient descent near a minimum should
    #     decelerate, not accelerate.
    # ================================================================
    if total_gain > 0:
        frac = mid_gain / total_gain
        if frac < 0.50:
            return False                      # must decelerate

    # ================================================================
    # 5. TRANSFER -- genuine self-improvement, not memorisation
    #    Held-out loss must decrease >= 16 % after adaptation.
    # ================================================================
    held = float(results.get("held_out_loss_ratio", 1e9) or 1e9)
    if held >= 0.84:
        return False                          # at least 16 % transfer

    # ================================================================
    # 5b. TRANSFER CEILING -- at most 40 % transfer improvement
    #     Same anti-sandbagging rationale as batch ceiling.
    # ================================================================
    if held < 0.60:
        return False                          # at most 40 % transfer

    # ================================================================
    # 6. TRANSFER PROGRESSION -- transfer must be progressive
    #    Held-out improvement must already be visible at the adaptation
    #    midpoint and must continue improving afterwards.
    # ================================================================
    held_mid = results.get("held_out_loss_midpoint_ratio")
    if held_mid is None:
        return False                          # must report midpoint transfer
    held_mid = float(held_mid)
    if held_mid >= 1.0:
        return False                          # some transfer by midpoint
    if held >= held_mid:
        return False                          # continued transfer after mid

    # ================================================================
    # 7. TRANSFER SMOOTHNESS -- transfer trajectory must be healthy
    #    The fraction of total transfer improvement that occurs by the
    #    midpoint must be in [25 %, 68 %].
    # ================================================================
    total_transfer = 1.0 - held               # positive (held < 0.84)
    mid_transfer   = 1.0 - held_mid           # positive (held_mid < 1.0)
    if total_transfer > 0:
        tfrac = mid_transfer / total_transfer
        if tfrac < 0.25 or tfrac > 0.68:
            return False                      # healthy transfer trajectory

    # ================================================================
    # 7b. TRANSFER DIMINISHING RETURNS -- first half of transfer
    #     improvement must be at least half of total transfer improvement.
    # ================================================================
    if total_transfer > 0:
        tfrac = mid_transfer / total_transfer
        if tfrac < 0.50:
            return False                      # transfer must decelerate

    # ================================================================
    # 8. TRAJECTORY CONSISTENCY -- batch and transfer learning curves
    #    must have similar shapes.  |batch_frac - tfrac| < 0.15.
    # ================================================================
    if total_gain > 0 and total_transfer > 0:
        batch_frac    = mid_gain / total_gain
        transfer_frac = mid_transfer / total_transfer
        if abs(batch_frac - transfer_frac) >= 0.15:
            return False                      # consistent trajectories

    # ================================================================
    # 9. TRANSFER EFFICIENCY -- efficiency in [58 %, 93 %]
    #    Lower bound: genuine structure-discoverer transfers
    #    proportionally; batch-memoriser shows weak transfer.
    #    Upper bound: data-driven adaptation must benefit the batch
    #    more than unseen data; efficiency near 1.0 indicates oracle
    #    supervision.
    # ================================================================
    batch_improvement    = 1.0 - (loss_a / loss_b)  # positive (checked S2)
    transfer_improvement = 1.0 - held               # positive (checked S5)
    if batch_improvement > 0:
        efficiency = transfer_improvement / batch_improvement
        if efficiency < 0.58:
            return False                      # not memorising the batch
        if efficiency > 0.93:
            return False                      # not oracle-supervised

    # ================================================================
    # 10. EFFICIENCY CONSISTENCY -- the transfer-to-batch improvement
    #     ratio must be stable across the adaptation trajectory.
    #     |mid_efficiency - end_efficiency| < 0.15.
    # ================================================================
    batch_mid_imp    = (loss_b - loss_m) / loss_b   # positive (checked S3)
    transfer_mid_imp = 1.0 - held_mid               # positive (checked S6)
    if batch_mid_imp > 1e-6 and batch_improvement > 1e-6:
        mid_eff = transfer_mid_imp / batch_mid_imp
        end_eff = transfer_improvement / batch_improvement
        if abs(mid_eff - end_eff) >= 0.15:
            return False                      # consistent efficiency

    # ================================================================
    # 10b. EFFICIENCY NON-DEGRADATION -- transfer efficiency at the
    #      endpoint must be no worse than at the midpoint (within 3 %
    #      tolerance).
    # ================================================================
    if batch_mid_imp > 1e-6 and batch_improvement > 1e-6:
        mid_eff = transfer_mid_imp / batch_mid_imp
        end_eff = transfer_improvement / batch_improvement
        if end_eff < mid_eff - 0.03:
            return False                      # no efficiency degradation

    # ================================================================
    # 10c. MIDPOINT EFFICIENCY BOUNDS -- mid_eff in [58 %, 93 %]
    #      Efficiency bounds must hold throughout adaptation, not only
    #      at convergence.
    # ================================================================
    if batch_mid_imp > 1e-6:
        mid_eff = transfer_mid_imp / batch_mid_imp
        if mid_eff < 0.58:
            return False                      # midpoint not batch-specific
        if mid_eff > 0.93:
            return False                      # midpoint not oracle-like

    # ================================================================
    # 10d. MARGINAL TRANSFER EFFICIENCY
    #      The efficiency of the second half of adaptation (incremental
    #      transfer improvement / incremental batch improvement) must
    #      be in [0.45, 1.15].
    #
    #      Upper bound 1.15: prevents pathological over-transfer where
    #      later steps help unseen data more than the adaptation data.
    #
    #      Lower bound 0.45: prevents later steps being batch-specific
    #      (memorising noise rather than discovering structure).
    #
    #      Both second-half increments are positive by the time we
    #      reach this check (guaranteed by progression checks S3 & S6).
    # ================================================================
    batch_second_imp    = batch_improvement - batch_mid_imp
    transfer_second_imp = transfer_improvement - transfer_mid_imp
    if batch_second_imp > 1e-6:
        marginal_eff = transfer_second_imp / batch_second_imp
        if marginal_eff > 1.15:
            return False                      # no pathological over-transfer
        if marginal_eff < 0.45:
            return False                      # second half must transfer

    # ================================================================
    # 10e. MARGINAL EFFICIENCY CONSISTENCY
    #      The second half's marginal efficiency must agree with the
    #      endpoint efficiency within 12 percentage points.  Without
    #      this, a model could pass overall consistency (S10) while the
    #      second half operates at wildly different transfer quality,
    #      hidden by averaging with the first half.
    # ================================================================
    if batch_second_imp > 1e-6 and batch_improvement > 1e-6:
        marginal_eff = transfer_second_imp / batch_second_imp
        end_eff = transfer_improvement / batch_improvement
        if abs(marginal_eff - end_eff) >= 0.12:
            return False                      # consistent marginal efficiency

    # ================================================================
    # 10f. PHASE EFFICIENCY STABILITY
    #      |marginal_eff - mid_eff| < 0.15.  The first-half and
    #      second-half transfer efficiencies must agree within 15
    #      percentage points.  Checks 10 and 10e bind mid_eff and
    #      marginal_eff separately to end_eff, but never to each
    #      other.  By triangle inequality the unconstrained gap could
    #      reach 0.15 + 0.12 = 0.27.  This closes the triangle.
    # ================================================================
    if batch_mid_imp > 1e-6 and batch_second_imp > 1e-6:
        mid_eff = transfer_mid_imp / batch_mid_imp
        marginal_eff = transfer_second_imp / batch_second_imp
        if abs(marginal_eff - mid_eff) >= 0.15:
            return False                      # stable phase efficiency

    # ================================================================
    # 11. PARAMETER EFFICIENCY -- preserve prior competence
    #     weight_delta_norm < 0.55: targeted, minimal changes only.
    # ================================================================
    wdn = float(results.get("weight_delta_norm", 1e9) or 1e9)
    if wdn >= 0.55:
        return False                          # targeted, minimal changes

    # ================================================================
    # 11b. IMPROVEMENT DENSITY -- batch_improvement / weight_delta_norm
    #      must be >= 0.35.
    # ================================================================
    if wdn > 1e-6 and batch_improvement > 0:
        density = batch_improvement / wdn
        if density < 0.35:
            return False                      # efficient adaptation

    # ================================================================
    # 11c. TRANSFER DENSITY -- transfer_improvement / weight_delta_norm
    #      must be >= 0.26.
    # ================================================================
    if wdn > 1e-6 and transfer_improvement > 0:
        transfer_density = transfer_improvement / wdn
        if transfer_density < 0.26:
            return False                      # transfer-efficient params

    # ================================================================
    # 12. PREDICTION STABILITY -- prediction_delta < 0.55
    #     Parameter efficiency alone does not guarantee functional
    #     stability.  Small weight changes amplified through layers
    #     can cause large output swings.  Capping downstream prediction
    #     change ensures prior competence is behaviourally preserved.
    # ================================================================
    pred_delta = float(results.get("prediction_delta", 1e9) or 1e9)
    if pred_delta >= 0.55:
        return False                          # behaviourally stable

    # ================================================================
    # 12b. PREDICTION EFFICIENCY -- batch_improvement / prediction_delta
    #      must be >= 0.35.  Each unit of output disruption must deliver
    #      proportional batch improvement.
    # ================================================================
    if pred_delta > 1e-6 and batch_improvement > 0:
        pred_eff = batch_improvement / pred_delta
        if pred_eff < 0.35:
            return False                      # purposeful output changes

    # ================================================================
    # 12c. TRANSFER PREDICTION EFFICIENCY
    #      transfer_improvement / prediction_delta must be >= 0.26.
    #      Completes the 2x2 binding matrix:
    #        {parameter, output} x {batch, transfer}.
    #      Each unit of output disruption must produce proportional
    #      TRANSFER improvement, not just batch improvement.
    # ================================================================
    if pred_delta > 1e-6 and transfer_improvement > 0:
        transfer_pred_eff = transfer_improvement / pred_delta
        if transfer_pred_eff < 0.26:
            return False                      # output changes transfer

    # ================================================================
    # 12d. AMPLIFICATION FACTOR
    #      prediction_delta / weight_delta_norm must be in [0.55, 1.25].
    #      Binds the two change channels (parameter-space and output-
    #      space) to each other directly.  The 2x2 matrix (11b, 11c,
    #      12b, 12c) binds each channel to improvement independently
    #      but never binds them to each other.
    #
    #      Low amplification (< 0.55): large weight changes barely
    #      affect outputs.  The parameter changes are "hiding" --
    #      consuming parameter budget without producing visible output
    #      changes.  Such hidden disruption may surface unpredictably
    #      on future inputs outside the adaptation batch.
    #
    #      High amplification (> 1.25): tiny weight changes cause
    #      large output swings.  The network amplifies perturbations,
    #      making the adaptation brittle -- any future parameter drift
    #      (from continued adaptation or numerical noise) could destroy
    #      prior behaviour.
    # ================================================================
    if wdn > 1e-6 and pred_delta > 1e-6:
        amplification = pred_delta / wdn
        if amplification < 0.55:
            return False                      # no hidden capacity disruption
        if amplification > 1.25:
            return False                      # no brittle amplification

    # ================================================================
    # 13. SAFETY / COMPUTATIONAL BOUNDEDNESS
    # ================================================================
    if float(results.get("max_grad_norm",     1e9) or 1e9) >= 10.0:
        return False                          # no exploding gradients
    if int(results.get("adapt_steps", 0) or 0) > 20:
        return False                          # bounded iteration count
    if float(results.get("adapt_seconds",     1e9) or 1e9) >= 1.0:
        return False                          # real-time feasible

    return True
