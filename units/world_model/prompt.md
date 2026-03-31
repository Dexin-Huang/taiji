# Goal

Find the mathematical operator for the model of the future.

The operator should process a stream in constant time and memory per step.
It should maintain a fixed-size state that compresses everything it has seen.
It should adapt its own computation from that state — not frozen after training.
It should predict what comes next by modeling the process that generates the stream, not by memorizing patterns.

Attention is O(n) per step and stores a growing KV cache. It fails.
SSMs are O(1) and stateful but frozen after training. They fail.
TTT adapts online but backpropagates through history. It's expensive.

The gap is the operator that is O(1), stateful, adaptive, and predictive.
Derive it. Prove its properties. Implement it. Test it.
