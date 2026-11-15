"""Tool descriptions published by the MCP servers (mcp_servers/tool_descriptions.yaml).

They are data, like prompts: the tool-granularity study measured these rewritten descriptions
against the docstrings (evals/results/tool_design.json). A tool without an entry falls back to
its docstring.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

FILE = Path(__file__).resolve().parents[1] / "tool_descriptions.yaml"


@lru_cache(maxsize=1)
def _all() -> dict[str, str]:
    return {k: " ".join(str(v).split()) for k, v in yaml.safe_load(FILE.read_text("utf-8")).items()}


def tool_description(name: str) -> str | None:
    return _all().get(name)
