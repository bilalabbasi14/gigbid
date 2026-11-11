"""Print the API's OpenAPI schema (no server start). `make openapi-client` pipes it into
apps/web/openapi.json and regenerates the TypeScript client, which is never hand-edited."""

from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("GIGBID_WARM_MODELS", "0")

from apps.api.main import app  # noqa: E402


def main() -> None:
    json.dump(app.openapi(), sys.stdout, indent=2)


if __name__ == "__main__":
    main()
