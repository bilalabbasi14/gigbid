"""R&D question A: does tool granularity change agent behaviour?

Three tool sets over the same 18 capabilities, built from the MCP schema snapshots frozen in
evals/datasets/tool_surface_docstrings/ (the surface as measured):
  A fine    - one tool per capability (the MCP tools with their docstring descriptions)
  B coarse  - three tools (marketplace, portfolio, workspace) taking {operation, arguments}
  C best    - the fine-grained tools with rewritten descriptions (evals/datasets/tool_descriptions_v2.yaml)

For each of the 40 tasks in evals/datasets/tool_tasks.jsonl the model must make exactly one tool
call. We score tool-selection accuracy, argument accuracy (every expected argument present with
the right value) and tokens per task. The same model is used for every set and rate limits are
retried on that model, never answered by a fallback, so differences come from the tools alone.

  uv run python -m evals.runners.tool_design_eval [--sets fine,coarse,best] [--spec groq:openai/gpt-oss-20b]
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import time
from typing import Any

import yaml
from langchain_core.messages import HumanMessage, SystemMessage

from agent import llm, settings
from evals.runners.harness import write_result

ROOT = settings.ROOT
# the tool surface as it was measured (docstring descriptions); the servers now publish set C
SNAP = ROOT / "evals/datasets/tool_surface_docstrings"
SERVERS = ("marketplace", "portfolio", "workspace")
SYSTEM = "You operate a freelancer's marketplace, portfolio and calendar through tools. For the user's request, make exactly one tool call with the correct arguments. Do not answer in prose."


def _deref(schema: dict[str, Any]) -> dict[str, Any]:
    """Inline $ref/$defs so every provider accepts the schema."""
    defs = schema.get("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(copy.deepcopy(defs[node["$ref"].split("/")[-1]]))
            return {k: walk(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node

    return walk(schema)


def load_fine() -> dict[str, dict[str, Any]]:
    tools: dict[str, dict[str, Any]] = {}
    for server in SERVERS:
        snap = json.loads((SNAP / f"{server}.json").read_text(encoding="utf-8"))
        for name, t in snap.items():
            if name.startswith("__"):
                continue
            tools[name] = {
                "server": server,
                "description": t["description"] or t["title"] or name,
                "parameters": _deref(t["inputSchema"]),
            }
    return tools


def toolset(kind: str) -> tuple[list[dict[str, Any]], dict[str, str]]:
    fine = load_fine()
    if kind == "fine":
        return [
            {
                "type": "function",
                "function": {
                    "name": n,
                    "description": t["description"],
                    "parameters": t["parameters"],
                },
            }
            for n, t in fine.items()
        ], {n: t["server"] for n, t in fine.items()}
    if kind == "best":
        desc = yaml.safe_load(
            (ROOT / "evals/datasets/tool_descriptions_v2.yaml").read_text(encoding="utf-8")
        )
        return [
            {
                "type": "function",
                "function": {
                    "name": n,
                    "description": desc.get(n, t["description"]),
                    "parameters": t["parameters"],
                },
            }
            for n, t in fine.items()
        ], {n: t["server"] for n, t in fine.items()}
    tools = []
    for server in SERVERS:
        ops = [n for n, t in fine.items() if t["server"] == server]
        lines = "; ".join(f"{n}: {fine[n]['description'].split('.')[0][:110]}" for n in ops)
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": server,
                    "description": f"All {server} operations. Choose `operation` and pass its arguments in `arguments`. Operations: {lines}",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "operation": {"type": "string", "enum": ops},
                            "arguments": {
                                "type": "object",
                                "description": "arguments for the chosen operation",
                            },
                        },
                        "required": ["operation", "arguments"],
                    },
                },
            }
        )
    return tools, {n: t["server"] for n, t in fine.items()}


def _get(args: dict[str, Any], dotted: str) -> Any:
    cur: Any = args
    for part in dotted.split("."):
        if isinstance(cur, str):
            try:
                cur = json.loads(cur)
            except json.JSONDecodeError:
                return None
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _same(expected: Any, got: Any) -> bool:
    if got is None:
        return False
    if isinstance(expected, bool):
        return got is expected or str(got).lower() == str(expected).lower()
    if isinstance(expected, int | float) and not isinstance(expected, bool):
        try:
            return abs(float(got) - float(expected)) < 1e-6
        except (TypeError, ValueError):
            return False
    if isinstance(expected, list):
        return isinstance(got, list) and {str(x).lower() for x in expected} <= {
            str(x).lower() for x in got
        }
    e, g = str(expected).lower().strip(), str(got).lower().strip()
    return e == g or g.startswith(e) or e in g


def score_call(
    task: dict[str, Any],
    kind: str,
    name: str | None,
    args: dict[str, Any],
    server_of: dict[str, str],
) -> tuple[bool, float]:
    if name is None:
        return False, 0.0
    if kind == "coarse":
        selected = name == server_of[task["tool"]] and args.get("operation") == task["tool"]
        inner = args.get("arguments") or {}
        if isinstance(inner, str):
            try:
                inner = json.loads(inner)
            except json.JSONDecodeError:
                inner = {}
    else:
        selected = name == task["tool"]
        inner = args
    exp = task["args"]
    if not exp:
        return selected, 1.0 if selected else 0.0
    hits = sum(1 for k, v in exp.items() if _same(v, _get(inner, k)))
    return selected, (hits / len(exp)) if selected else 0.0


async def ask(
    model: Any, task: dict[str, Any]
) -> tuple[str | None, dict[str, Any], dict[str, int], float]:
    msgs = [SystemMessage(content=SYSTEM), HumanMessage(content=task["request"])]
    for attempt in range(12):
        t0 = time.perf_counter()
        try:
            resp = await model.ainvoke(msgs)
            break
        except Exception as exc:  # noqa: BLE001
            if llm.is_daily_cap(exc):  # not worth retrying; the run resumes from saved rows
                raise llm.QuotaExhaustedError(str(exc)[:300]) from exc
            text = f"{type(exc).__name__} {exc}".lower()
            if (
                "429" in text
                or "rate" in text
                or "connection" in text
                or "timeout" in text
                or "503" in text
            ):
                await asyncio.sleep(min(60, 10 + 5 * attempt))
                continue
            if "tool_use_failed" in text or "failed to call a function" in text:
                return None, {}, {}, time.perf_counter() - t0  # the model produced an invalid call
            raise
    else:
        raise RuntimeError("rate limited too long")
    calls = getattr(resp, "tool_calls", None) or []
    u = getattr(resp, "usage_metadata", None) or {}
    usage = {
        "input_tokens": int(u.get("input_tokens", 0)),
        "output_tokens": int(u.get("output_tokens", 0)),
    }
    if not calls:
        return None, {}, usage, time.perf_counter() - t0
    return calls[0]["name"], calls[0].get("args") or {}, usage, time.perf_counter() - t0


ROWS = ROOT / "evals/results/tool_design_rows.jsonl"


def _done(kind: str, spec: str) -> dict[str, dict[str, Any]]:
    """Rows already measured for this tool set and model (the run resumes after a crash)."""
    if not ROWS.exists():
        return {}
    out = {}
    for line in ROWS.open(encoding="utf-8"):
        r = json.loads(line)
        if r["tool_set"] == kind and r["model"] == spec:
            out[r["id"]] = r
    return out


async def run(kind: str, spec: str, tasks: list[dict[str, Any]]) -> dict[str, Any]:
    tools, server_of = toolset(kind)
    model = llm.chat_model(spec, temperature=0.0, max_tokens=600).bind_tools(
        tools, tool_choice="required"
    )
    done = _done(kind, spec)
    rows = []
    for t in tasks:
        if t["id"] in done:
            rows.append(done[t["id"]])
            continue
        name, args, usage, dt = await ask(model, t)
        sel, arg_score = score_call(t, kind, name, args, server_of)
        row = {
            "tool_set": kind,
            "model": spec,
            "id": t["id"],
            "expected": t["tool"],
            "called": name,
            "args": args,
            "selected_ok": sel,
            "arg_score": round(arg_score, 3),
            "args_ok": sel and arg_score == 1.0,
            "tokens": sum(usage.values()),
            "input_tokens": usage.get("input_tokens", 0),
            "latency_s": round(dt, 2),
        }
        rows.append(row)
        with ROWS.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")
        print(
            f"  [{kind:6s}] {t['id']} expected={t['tool']:22s} called={name!s:22s} sel={sel!s:5s} args={arg_score:.2f}"
        )
    n = len(rows)
    return {
        "tool_set": kind,
        "n_tools": len(tools),
        "schema_tokens_estimate": len(json.dumps(tools)) // 4,
        "selection_accuracy": round(sum(r["selected_ok"] for r in rows) / n, 3),
        "argument_accuracy": round(sum(r["args_ok"] for r in rows) / n, 3),
        "mean_argument_score": round(sum(r["arg_score"] for r in rows) / n, 3),
        "tokens_per_task": round(sum(r["tokens"] for r in rows) / n, 1),
        "input_tokens_per_task": round(sum(r["input_tokens"] for r in rows) / n, 1),
        "rows": rows,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sets", default="fine,coarse,best")
    ap.add_argument(
        "--spec",
        default=None,
        help="provider:model (default: the small tier of the active profile)",
    )
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    spec = args.spec or settings.config().models.profiles[settings.config().models.profile].small
    tasks = [
        json.loads(line)
        for line in (ROOT / "evals/datasets/tool_tasks.jsonl").open(encoding="utf-8")
    ][: args.limit]
    results = {}
    for kind in [k for k in args.sets.split(",") if k]:
        try:
            results[kind] = asyncio.run(run(kind, spec, tasks))
        except llm.QuotaExhaustedError as exc:
            print(f"partial: {kind} stopped at the daily cap of {spec}; rerun later ({exc})"[:300])
            raise SystemExit(3) from exc
        r = results[kind]
        print(
            f"{kind}: selection {r['selection_accuracy']}  arguments {r['argument_accuracy']}  tokens/task {r['tokens_per_task']}"
        )
    summary = {k: {kk: vv for kk, vv in v.items() if kk != "rows"} for k, v in results.items()}
    path = write_result(
        "tool_design",
        {"model": spec, "n_tasks": len(tasks), "summary": summary, "results": results},
    )
    print(f"-> {path}")


if __name__ == "__main__":
    main()
