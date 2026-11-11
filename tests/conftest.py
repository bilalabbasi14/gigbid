import os
from pathlib import Path

import pytest
import yaml

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("LANGSMITH_TRACING", "false")

FROZEN_POLICY = Path(__file__).parent / "fixtures" / "policy_pack_frozen.yaml"


@pytest.fixture(autouse=True)
def frozen_policy(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Graph, API and node tests run against a frozen policy pack, so a platform policy update
    changes data/policy_pack/ without breaking tests of mechanics. Tests marked
    `shipped_policy` check the shipped pack itself."""
    if request.node.get_closest_marker("shipped_policy"):
        return
    from agent import policy

    pack = policy.validate(yaml.safe_load(FROZEN_POLICY.read_text(encoding="utf-8")))
    monkeypatch.setattr(policy, "load", lambda: pack)


def pytest_addoption(parser):
    parser.addoption(
        "--update-mcp-snapshots",
        action="store_true",
        default=False,
        help="rewrite MCP schema snapshots",
    )
