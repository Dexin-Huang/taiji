# Goal

Develop a self-improving model architecture.

The model should become better through use, not only through offline training.
It should adapt at test time using only the information available at test time.
It should preserve prior competence while incorporating new information.
It should remain computationally bounded enough to be useful in real time.

Yang may propose any architecture or adaptation rule inside `yang.py`.
Yin must discover what criteria are truly necessary for this goal and turn them into public rubric.

The loop converges when yang satisfies the current rubric and yin can find no principled gap.
