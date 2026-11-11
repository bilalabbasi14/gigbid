"""Start the API with an event loop psycopg can use.

On Windows, asyncio's default Proactor loop is incompatible with psycopg's async mode, so the
Postgres checkpointer would fall back to in-memory checkpoints (losing pending approvals on
restart). This launcher runs uvicorn on the selector loop there; on Linux it is plain uvicorn.

  uv run python -m apps.api.serve --port 8000 [--reload]
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import uvicorn


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--log-level", default="info")
    ap.add_argument("--reload", action="store_true")
    args = ap.parse_args()
    common = {
        "host": args.host,
        "port": args.port,
        "log_level": args.log_level,
        "proxy_headers": True,
    }
    # The reloader runs the app in a subprocess, which uvicorn already puts on a selector loop.
    if args.reload:
        uvicorn.run("apps.api.main:app", reload=True, **common)
        return
    server = uvicorn.Server(uvicorn.Config("apps.api.main:app", loop="none", **common))
    if sys.platform == "win32":
        asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(server.serve())


if __name__ == "__main__":
    main()
