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
    Return True if yang's latest results count as a pass in the current world.

    Keep this law simple and public.
    If yang passes too easily, wake and rewrite world() and/or passes(results).
    """
    return False
