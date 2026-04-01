def world() -> dict:
    """
    Return a JSON-serializable world specification.

    The host will write it to world.json before yang runs.
    Keep it minimal, explicit, and deterministic enough to be learnable.
    """
    return {
        # "seed": 0,
    }


def passes(results: dict) -> bool:
    """
    Return True if yang's latest JSON submission counts as a pass in the current world.

    Keep this law simple and public.
    You may inspect nested evidence and the implementation in yang.py directly.
    If yang passes too easily, wake and rewrite world() and/or passes(results).
    """
    return False
