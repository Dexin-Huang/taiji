# Goal

Develop a persistent self-improving model architecture.

The model should become better through use, not only through offline training.
It should adapt online using only the information available at test time.
It should keep useful state across a stream instead of recomputing everything from scratch.
It should preserve useful knowledge across later chunks of the same world.
It should remain computationally bounded enough to be useful in real time.

Yang may propose any architecture or adaptation rule inside `yang.py`.
Yin must discover what kind of world makes persistent self-improvement actually necessary,
then decide what counts as a pass.

The loop converges when yang satisfies the current world and yin can find no principled gap.
