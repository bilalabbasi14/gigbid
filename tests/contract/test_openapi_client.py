"""The TypeScript client is generated from apps/web/openapi.json. This fails when the FastAPI
schema changed without regenerating it (`make openapi-client`), so the web app never drifts from
the API contract."""

from __future__ import annotations

import json
import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("GIGBID_WARM_MODELS", "0")

from agent.settings import ROOT  # noqa: E402


def test_committed_openapi_matches_api():
    from apps.api.main import app

    committed = json.loads((ROOT / "apps/web/openapi.json").read_text(encoding="utf-8"))
    current = json.loads(json.dumps(app.openapi()))
    assert committed["paths"].keys() == current["paths"].keys(), (
        "endpoints changed: run `make openapi-client`"
    )
    assert committed == current, "API schema changed: run `make openapi-client` and commit apps/web"
    assert (ROOT / "apps/web/src/lib/api/schema.d.ts").exists()
