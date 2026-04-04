def compile_candidate(candidate: dict, witness: dict) -> dict:
    """
    Optional compiled reference implementation for a mechanism-search unit.

    Read world.json, yin.py, problem_spec.md, candidate.json, witness.json,
    and derivation.md when useful.

    The host evaluates candidate.json, witness.json, and derivation.md
    directly. This file is for executable sanity checks or a reference
    implementation of the accepted mechanism.
    """
    compiled = {
        "candidate": candidate,
        "witness": witness,
    }

    # --- optional reference implementation here ---

    return compiled
