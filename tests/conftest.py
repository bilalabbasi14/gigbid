import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("LANGSMITH_TRACING", "false")


def pytest_addoption(parser):
    parser.addoption(
        "--update-mcp-snapshots", action="store_true", default=False, help="rewrite MCP schema snapshots"
    )
