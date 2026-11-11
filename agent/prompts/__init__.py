"""Prompt loader: every prompt is a versioned markdown file in this directory.

File format:
    ---
    version: 2
    node: writer
    ---
    ## system
    ...
    ## user
    ...  (with {placeholders} filled by str.format)
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

PROMPTS_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=64)
def load_prompt(name: str) -> tuple[str, str]:
    """Return (system, user) templates for prompt `name` (file name without .md)."""
    path = PROMPTS_DIR / f"{name}.md"
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if m:
        text = text[m.end() :]
    parts = re.split(r"^##\s+(system|user)\s*$", text, flags=re.M)
    sections = {parts[i].lower(): parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
    return sections.get("system", ""), sections.get("user", "")


def prompt_version(name: str) -> int:
    path = PROMPTS_DIR / f"{name}.md"
    m = re.match(r"^---\n(.*?)\n---\n", path.read_text(encoding="utf-8"), re.S)
    meta = yaml.safe_load(m.group(1)) if m else {}
    return int((meta or {}).get("version", 1))
