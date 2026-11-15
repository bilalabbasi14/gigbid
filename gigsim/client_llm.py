"""The LLM side of a simulated client.

An open model reads one proposal the way that client would, using the client's hidden
preferences, and returns its interest (0 to 1), its concerns and the reply it would write.
`clients.decide` blends this with the rule score; the hidden preferences stay authoritative.

  GIGSIM_CLIENT_LLM         provider:model, `ollama:qwen3:4b-instruct` (default, free, local) or
                            `groq:<model>` (needs GROQ_API_KEY; fast enough for a hosted demo)
  GIGSIM_CLIENT_LLM_TIMEOUT seconds per call (default 180; decisions run in the background)
  GIGSIM_LLM_CACHE          JSON cache file; the same proposal always gets the same judgement

Every failure returns None and the client decides by rules alone (recorded in the breakdown).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger("gigsim.client_llm")
PROMPT = Path(__file__).parent / "prompts" / "client_decision.md"
_LOCK = threading.Lock()
_CACHE: dict[str, dict[str, Any]] | None = None


def spec() -> str:
    return os.environ.get("GIGSIM_CLIENT_LLM", "ollama:qwen3:4b-instruct")


def _cache_path() -> Path:
    default = (
        Path(__file__).resolve().parents[1] / "data" / "processed" / "gigsim_client_cache.json"
    )
    return Path(os.environ.get("GIGSIM_LLM_CACHE", str(default)))


def _load_cache() -> dict[str, dict[str, Any]]:
    global _CACHE
    if _CACHE is None:
        p = _cache_path()
        try:
            _CACHE = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        except (OSError, ValueError):
            _CACHE = {}
    return _CACHE


def _save_cache() -> None:
    p = _cache_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(_CACHE, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
    except OSError as exc:  # the cache is an optimisation; never fail a decision over it
        log.warning("client LLM cache not saved: %s", exc)


def _prompt() -> tuple[str, str]:
    text = PROMPT.read_text(encoding="utf-8")
    system = text.split("## system", 1)[1].split("## user", 1)[0].strip()
    user = text.split("## user", 1)[1].strip()
    return system, user


def _key(job: dict[str, Any], letter: str, bid: float, answers: list[str]) -> str:
    raw = json.dumps([spec(), job.get("job_id"), letter, bid, answers], ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _chat(system: str, user: str, timeout: float) -> str:
    provider, _, model = spec().partition(":")
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    if provider == "ollama":
        base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        r = httpx.post(
            f"{base}/api/chat",
            json={
                "model": model,
                "messages": msgs,
                "stream": False,
                "format": "json",
                "think": False,
                "keep_alive": "10m",
                "options": {"temperature": 0, "seed": 7, "num_ctx": 4096, "num_predict": 220},
            },
            timeout=timeout,
        )
        r.raise_for_status()
        return r.json()["message"]["content"]
    if provider == "groq":
        key = os.environ.get("GROQ_API_KEY")
        if not key:
            raise RuntimeError("GROQ_API_KEY is not set")
        body: dict[str, Any] = {
            "model": model,
            "messages": msgs,
            "temperature": 0,
            "seed": 7,
            "max_tokens": 300,
            "response_format": {"type": "json_object"},
        }
        if "gpt-oss" in model:
            body["reasoning_effort"] = "low"
        r = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json=body,
            timeout=timeout,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    raise ValueError(f"unknown client LLM provider in {spec()!r}")


def parse(text: str) -> dict[str, Any] | None:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        interest = max(0.0, min(1.0, float(data["interest"])))
    except (ValueError, KeyError, TypeError):
        return None
    concerns = [str(c)[:120] for c in (data.get("concerns") or [])][:3]
    reply = str(data.get("reply") or "").strip()[:600]
    return {"interest": round(interest, 3), "concerns": concerns, "reply": reply}


def judge(
    job: dict[str, Any], prefs: dict[str, Any], cover_letter: str, bid: float, answers: list[str]
) -> dict[str, Any] | None:
    """The client's reading of one proposal, or None if the model is unavailable."""
    key = _key(job, cover_letter, bid, answers)
    with _LOCK:
        hit = _load_cache().get(key)
    if hit:
        return {**hit, "cached": True}
    system, user = _prompt()
    visible = {k: v for k, v in prefs.items() if k not in ("never_replies",)}
    filled = user.format(
        title=job.get("title", ""),
        description=(job.get("description") or "")[:1500],
        questions="; ".join(job.get("screening_questions") or []) or "(none)",
        preferences=json.dumps(visible, ensure_ascii=False),
        bid=f"${bid:g}",
        cover_letter=cover_letter[:2500],
        answers="\n".join(answers) or "(none)",
    )
    try:
        out = parse(
            _chat(system, filled, float(os.environ.get("GIGSIM_CLIENT_LLM_TIMEOUT", "180")))
        )
    except Exception as exc:  # noqa: BLE001 - any failure means rules decide alone
        log.warning("client LLM unavailable (%s): %s", spec(), str(exc)[:200])
        return None
    if out is None:
        log.warning("client LLM returned no usable JSON (%s)", spec())
        return None
    out["model"] = spec()
    with _LOCK:
        _load_cache()[key] = out
        _save_cache()
    return out
