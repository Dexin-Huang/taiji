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


def score(results: dict) -> dict:
    """
    Optional public progress comparator for failed yang attempts.

    Return:
        {
            "order": [
                {"name": "metric_name", "value": 1.23, "direction": "min"},
            ],
            "summary": {
                "metric_name": 1.23,
            },
        }

    The host compares `order` lexicographically under the frozen law snapshot.
    Keep it aligned with passes(results). Use it only to say which failure is closer.
    Make it robust to partial, failed, or empty results too. Never raise, and
    never return NaN or infinity. Use finite fallback values when evidence is
    missing.
    """
    return {
        "order": [],
        "summary": {},
    }
