# Goal

Assemble the pieces into a single neural network layer.

The pieces already exist:

- **Delta rule fast weights** (Schmidhuber 1992, Schlag 2021) — O(1) outer-product update to a weight matrix used as associative memory
- **TTT-Linear** (Sun 2024) — gradient descent on inner model weights at inference time, with a learned learning rate
- **Gated Delta Networks** (Yang 2024) — input-dependent gating that controls how much to update the fast weight matrix per step
- **Mamba selectivity** (Gu 2023) — input-dependent state transition matrices, O(1) linear recurrence
- **DeltaProduct** (Clark 2025) — products of Householder reflections to increase expressivity of delta-rule state

The target is a PyTorch `nn.Module` with `forward(x_t, state) -> (logits, new_state)` that has all four properties:

1. O(1) time and memory per step
2. Fixed-size hidden state
3. Updates its own parameters from the stream at inference time
4. Predicts next token

These pieces have never been composed into a single operator. The insight is the composition — like how attention composed queries (information retrieval), key-value stores (databases), and softmax (logistic regression) into one differentiable operation.

Yang should search the literature (use WebSearch), understand each piece, then find the composition. Implement it as a trainable `nn.Module`. Train it on a real sequence task. Show each piece is load-bearing by ablating it.

Yin should verify that every component contributes. If removing any piece doesn't degrade performance, that piece is dead weight and the solution is a dressed-up version of something that already exists. Reject it.
