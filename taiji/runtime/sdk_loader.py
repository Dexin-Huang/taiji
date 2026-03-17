"""
Helpers for importing the Claude Agent SDK from either an installed package
or the local reference checkout.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .schema import ROOT

REFERENCE_SDK_SRC = ROOT / "references" / "claude-agent-sdk-python" / "src"


def load_claude_agent_sdk():
    try:
        import claude_agent_sdk  # type: ignore
    except ImportError:
        if REFERENCE_SDK_SRC.exists():
            reference_path = str(REFERENCE_SDK_SRC)
            if reference_path not in sys.path:
                sys.path.insert(0, reference_path)
        try:
            import claude_agent_sdk  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "Claude Agent SDK is not importable. Install `claude-agent-sdk` or keep a local clone at "
                f"{REFERENCE_SDK_SRC}."
            ) from exc
    return claude_agent_sdk


def claude_sdk_reference_root() -> Path:
    return REFERENCE_SDK_SRC.parent
