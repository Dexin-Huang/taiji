# Goal

Derive the equation for a neural network layer that does all four:

1. O(1) time and memory per step (no growing cache, no attention over history)
2. Maintains a fixed-size hidden state that compresses the stream
3. Updates its own parameters from the stream at inference time (not frozen after training)
4. Predicts the next token

No existing architecture does all four. Transformers fail 1-2. SSMs/Mamba/RWKV/xLSTM fail 3. TTT fails 1.

The deliverable is a PyTorch `nn.Module` with a `forward(x_t, state) -> (logits, new_state)` signature. Train it on a real task. Show it works. Show property 3 is real — that the layer's predictions improve on a distribution shift without any gradient from the training loss.
