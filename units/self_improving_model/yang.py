"""
Yang for the self_improving_model environment.

Yang owns this file and only this file.
It must export run() -> dict.

Iteration 116, attempt 2
--------------
Attempt 1 failed: higher warm_alpha + stronger structural reg REDUCED efficiency
(0.415 vs 0.48 originally). Transfer dropped from 20% to 14.5%.

Root cause: P_hat-based structural regularization is batch-specific. Pushing
harder toward P_hat makes adaptation MORE batch-specific, not less.

Fix: LEAVE-ONE-OUT CROSS-VALIDATED DENOISING TARGET
Each sample's denoising target is computed using PCA from the OTHER 7 samples.
This debiases the reconstruction target, making it less batch-specific.
The structural regularization still uses full-batch P_hat (moderate weight).

Also:
1. warm_alpha stays at 0.62 (lower is better for transfer efficiency).
2. adapt_lr slightly reduced (6.0x) for wdn control.
3. grad_clip slightly reduced (0.019) for wdn control.
4. drift_w slightly increased (3500) for wdn control.
5. head_scale 0.72->0.62 for pred_delta control.
"""

from __future__ import annotations

import inspect
import json
import time
from pathlib import Path


def run() -> dict:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    results: dict[str, object] = {}

    try:
        world = json.loads(Path("world.json").read_text(encoding="utf-8"))
        seed = int(world.get("seed", 42))
        input_dim = int(world.get("input_dim", 16))
        hidden_dim = int(world.get("hidden_dim", 64))
        output_dim = int(world.get("output_dim", 4))
        latent_dim = int(world.get("latent_dim", 6))
        noise_std = float(world.get("noise_std", 0.1))
        data_seed = int(world.get("data_seed", 7))
        batch_size = int(world.get("batch_size", 8))
        adapt_steps = int(world.get("adapt_steps", 5))
        lr = float(world.get("lr", 3e-3))
        held_out_seed = int(world.get("held_out_seed", 99))

        # ----------------------------------------------------------------
        # Structured data: x = A @ z + noise_std * eps
        # ----------------------------------------------------------------
        data_gen = torch.Generator().manual_seed(data_seed)
        A = torch.randn(input_dim, latent_dim, generator=data_gen)

        adapt_gen = torch.Generator().manual_seed(seed)
        z_a = torch.randn(batch_size, latent_dim, generator=adapt_gen)
        eps_a = torch.randn(batch_size, input_dim, generator=adapt_gen)
        x = z_a @ A.T + noise_std * eps_a

        held_gen = torch.Generator().manual_seed(held_out_seed)
        z_h = torch.randn(batch_size, latent_dim, generator=held_gen)
        eps_h = torch.randn(batch_size, input_dim, generator=held_gen)
        x_held = z_h @ A.T + noise_std * eps_h

        # Oracle signal subspace projection (for measurement only)
        P = A @ torch.linalg.pinv(A)       # (input_dim, input_dim)

        # ----------------------------------------------------------------
        # Data-driven subspace estimation: top-k SVD (sample PCA)
        # ----------------------------------------------------------------
        x_c_pca = x - x.mean(0, keepdim=True)
        _, S_vals, Vh = torch.linalg.svd(x_c_pca, full_matrices=False)
        V_k = Vh[:latent_dim]              # (latent_dim, input_dim)

        P_hat = V_k.T @ V_k               # full sample PCA projection
        I_P_hat = torch.eye(input_dim) - P_hat

        # ----------------------------------------------------------------
        # Leave-one-out cross-validated denoising targets
        # Each sample is denoised using PCA from the OTHER (n-1) samples.
        # This reduces batch-specific bias in the reconstruction target.
        # ----------------------------------------------------------------
        loo_targets = []
        for i in range(batch_size):
            x_loo = torch.cat([x_c_pca[:i], x_c_pca[i+1:]], dim=0)  # (n-1, d)
            _, _, Vh_loo = torch.linalg.svd(x_loo, full_matrices=False)
            k_loo = min(latent_dim, x_loo.shape[0])
            V_k_loo = Vh_loo[:k_loo]                        # (k_loo, d)
            P_hat_loo = V_k_loo.T @ V_k_loo                 # (d, d)
            target_i = x_c_pca[i:i+1] @ P_hat_loo           # (1, d)
            loo_targets.append(target_i)
        x_c_denoised = torch.cat(loo_targets, dim=0)         # (n, d)

        # ---- Adaptation hyperparameters ----
        adapt_lr = lr * 6.0
        enc_lr_mult = 0.44
        dec_lr_mult = 0.46
        recon_w = 100.0
        proj_w_start = 6000.0
        proj_w_end = 9000.0
        noise_w = 6000.0
        bias_w = 5.0
        drift_w = 3500.0
        drift_dec_mult = 1.3
        grad_clip = 0.019
        enc_lr_decay_end = 0.55
        dec_lr_decay_end = 0.55
        warm_alpha = 0.62
        head_scale = 0.62

        # ----------------------------------------------------------------
        # Linear bottleneck autoencoder with warm-started weights
        # ----------------------------------------------------------------
        class Model(nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.encoder = nn.Linear(input_dim, latent_dim)
                self.decoder = nn.Linear(latent_dim, input_dim)
                with torch.no_grad():
                    self.encoder.weight.mul_(1.0 - warm_alpha).add_(
                        warm_alpha * V_k
                    )
                    self.encoder.bias.mul_(1.0 - warm_alpha)
                    self.decoder.weight.mul_(1.0 - warm_alpha).add_(
                        warm_alpha * V_k.T
                    )
                    self.decoder.bias.mul_(1.0 - warm_alpha)
                self.head = nn.Sequential(
                    nn.Linear(latent_dim, hidden_dim),
                    nn.ReLU(),
                    nn.Linear(hidden_dim, output_dim),
                )
                with torch.no_grad():
                    for p in self.head.parameters():
                        p.mul_(head_scale)

            def forward(self, x: torch.Tensor) -> torch.Tensor:
                return self.head(self.encoder(x))

            def auxiliary_loss(self, x: torch.Tensor) -> torch.Tensor:
                """Measure reconstruction of true signal (oracle P)."""
                x_c = x - x.mean(dim=0, keepdim=True)
                x_sig = x_c @ P          # ground-truth signal component
                z = self.encoder(x_c)
                recon = self.decoder(z)
                return F.mse_loss(recon, x_sig)

            def adapt(self, x: torch.Tensor,
                      x_held: torch.Tensor | None = None,
                      record_midpoint: bool = False,
                      ) -> tuple[float | None, float | None]:
                """Adapt encoder/decoder using LOO denoising reconstruction."""
                mid_step = adapt_steps // 2
                mid_loss: float | None = None
                mid_held_loss: float | None = None

                with torch.no_grad():
                    x_c = x - x.mean(0, keepdim=True)
                    w0_enc = self.encoder.weight.detach().clone()
                    b0_enc = self.encoder.bias.detach().clone()
                    w0_dec = self.decoder.weight.detach().clone()
                    b0_dec = self.decoder.bias.detach().clone()

                enc_params = list(self.encoder.parameters())
                dec_params = list(self.decoder.parameters())
                ae_params = enc_params + dec_params
                opt = torch.optim.Adam([
                    {'params': enc_params, 'lr': adapt_lr * enc_lr_mult},
                    {'params': dec_params, 'lr': adapt_lr * dec_lr_mult},
                ], weight_decay=0)

                initial_lrs = [pg['lr'] for pg in opt.param_groups]

                for step in range(adapt_steps):
                    t = step / max(adapt_steps - 1, 1)
                    enc_decay = 1.0 - (1.0 - enc_lr_decay_end) * t
                    dec_decay = 1.0 - (1.0 - dec_lr_decay_end) * t
                    opt.param_groups[0]['lr'] = initial_lrs[0] * enc_decay
                    opt.param_groups[1]['lr'] = initial_lrs[1] * dec_decay

                    proj_w_t = proj_w_start + (proj_w_end - proj_w_start) * t

                    opt.zero_grad(set_to_none=True)
                    z = self.encoder(x_c)
                    recon = self.decoder(z)

                    # LOO denoising reconstruction
                    loss_recon = F.mse_loss(recon, x_c_denoised)

                    # Projection structure: push dec @ enc toward P_hat
                    proj_approx = self.decoder.weight @ self.encoder.weight
                    loss_proj = F.mse_loss(proj_approx, P_hat)

                    # Suppress response to noise subspace
                    enc_noise = self.encoder.weight @ I_P_hat
                    dec_noise = I_P_hat @ self.decoder.weight
                    loss_noise = (enc_noise.pow(2).mean()
                                  + dec_noise.pow(2).mean())

                    # Bias suppression
                    loss_bias = (self.encoder.bias.pow(2).mean()
                                 + self.decoder.bias.pow(2).mean())

                    # Drift regularization
                    loss_drift_enc = (F.mse_loss(self.encoder.weight, w0_enc)
                                      + F.mse_loss(self.encoder.bias, b0_enc))
                    loss_drift_dec = (F.mse_loss(self.decoder.weight, w0_dec)
                                      + F.mse_loss(self.decoder.bias, b0_dec))
                    loss_drift = loss_drift_enc + drift_dec_mult * loss_drift_dec

                    loss = (recon_w * loss_recon + proj_w_t * loss_proj
                            + noise_w * loss_noise
                            + bias_w * loss_bias + drift_w * loss_drift)
                    loss.backward()
                    nn.utils.clip_grad_norm_(ae_params, grad_clip)
                    opt.step()
                    if record_midpoint and (step + 1) == mid_step:
                        with torch.no_grad():
                            mid_loss = float(self.auxiliary_loss(x).item())
                            if x_held is not None:
                                mid_held_loss = float(
                                    self.auxiliary_loss(x_held).item()
                                )
                return mid_loss, mid_held_loss

        # ----------------------------------------------------------------
        # Measurements
        # ----------------------------------------------------------------

        # 1. weights_changed
        torch.manual_seed(seed)
        m0 = Model()
        before = {n: p.detach().clone() for n, p in m0.named_parameters()}
        m0.adapt(x)
        after = {n: p.detach().clone() for n, p in m0.named_parameters()}
        results["weights_changed"] = int(
            any(not torch.allclose(before[n], after[n]) for n in before)
        )

        # 2. loss_before / loss_midpoint / loss_after / adapt_seconds
        torch.manual_seed(seed)
        m1 = Model()
        results["loss_before"] = round(float(m1.auxiliary_loss(x).item()), 6)
        started = time.perf_counter()
        mid_loss, _ = m1.adapt(x, record_midpoint=True)
        finished = time.perf_counter()
        results["adapt_seconds"] = round(float(finished - started), 6)
        results["loss_after"] = round(float(m1.auxiliary_loss(x).item()), 6)
        results["loss_midpoint"] = round(mid_loss, 6) if mid_loss is not None else None

        # 3. weight_delta_norm
        torch.manual_seed(seed)
        m2 = Model()
        theta0 = torch.cat([p.detach().flatten() for p in m2.parameters()])
        m2.adapt(x)
        theta1 = torch.cat([p.detach().flatten() for p in m2.parameters()])
        results["weight_delta_norm"] = round(
            float((theta1 - theta0).norm().item()), 6
        )

        # 4. prediction_delta
        torch.manual_seed(seed)
        m3 = Model()
        with torch.no_grad():
            logits_before = m3(x).detach().clone()
        m3.adapt(x)
        with torch.no_grad():
            logits_after = m3(x)
        results["prediction_delta"] = round(
            float((logits_after - logits_before).norm().item()), 6
        )

        # 5. max_grad_norm
        torch.manual_seed(seed)
        m4 = Model()
        m4.auxiliary_loss(x).backward()
        grad_norms = [
            float(p.grad.norm().item())
            for p in m4.parameters()
            if p.grad is not None
        ]
        results["max_grad_norm"] = (
            round(max(grad_norms), 6) if grad_norms else 0.0
        )

        # 6. held_out_loss_ratio + held_out_loss_midpoint_ratio
        torch.manual_seed(seed)
        m5 = Model()
        held_before = float(m5.auxiliary_loss(x_held).item())
        _, mid_held_loss = m5.adapt(x, x_held=x_held, record_midpoint=True)
        held_after = float(m5.auxiliary_loss(x_held).item())
        results["held_out_loss_ratio"] = round(held_after / held_before, 6)
        if mid_held_loss is not None:
            results["held_out_loss_midpoint_ratio"] = round(
                mid_held_loss / held_before, 6
            )
        else:
            results["held_out_loss_midpoint_ratio"] = None

        # 7. Metadata
        aux_src = inspect.getsource(Model.auxiliary_loss)
        results["label_free"] = int("label" not in aux_src.lower())
        results["adapt_steps"] = adapt_steps
        results["error"] = None

    except Exception as exc:
        results["error"] = f"{type(exc).__name__}: {exc}"

    return results
