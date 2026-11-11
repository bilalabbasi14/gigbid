"""Repository policy checks the assignment requires CI to enforce.

1. No secrets in the repo (pattern scan on tracked files; gitleaks runs separately in CI).
2. Nothing under gigsim/ changed (checksum lock, once gigsim/.lock.sha256 exists).
3. Every prompt lives in agent/prompts/ (no long prompt-like string literals in agent code).
4. Every number in README.md traces to a file in evals/results/ (numbers inside tables must sit
   in a row that cites a results file, or inside a <!-- results: path --> block).

Run: `python scripts/ci_checks.py`  (exit 1 on any violation)
Freeze gigsim/ the day the instructor's simulator is swapped in:
     `python scripts/ci_checks.py --freeze-gigsim`  (writes gigsim/.lock.sha256)
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SECRET_PATTERNS = [
    re.compile(r"gsk_[A-Za-z0-9]{20,}"),  # Groq
    re.compile(r"sk-or-v1-[A-Za-z0-9]{20,}"),  # OpenRouter
    re.compile(r"lsv2_[a-z]{2}_[A-Za-z0-9]{20,}"),  # LangSmith
    re.compile(r"sk-[A-Za-z0-9]{32,}"),  # OpenAI-style
    re.compile(r"AIza[0-9A-Za-z\-_]{30,}"),  # Google
    re.compile(r"ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}"),  # GitHub
    re.compile(r"pk-lf-[a-f0-9-]{20,}|sk-lf-[a-f0-9-]{20,}"),  # Langfuse
    re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]
TEXT_EXT = {
    ".py",
    ".md",
    ".yaml",
    ".yml",
    ".toml",
    ".json",
    ".ts",
    ".tsx",
    ".js",
    ".env",
    ".txt",
    ".cfg",
    ".ini",
    ".sh",
}


def tracked_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True)
    return [ROOT / p for p in out.stdout.splitlines() if p]


def check_secrets(files: list[Path]) -> list[str]:
    errors = []
    for f in files:
        if f.suffix not in TEXT_EXT and f.name != ".env.example":
            continue
        if not f.exists() or f.stat().st_size > 2_000_000:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pat in SECRET_PATTERNS:
            if pat.search(text):
                errors.append(f"possible secret matching {pat.pattern!r} in {f.relative_to(ROOT)}")
    if (ROOT / ".env").exists():
        tracked = {p.relative_to(ROOT).as_posix() for p in files}
        if ".env" in tracked:
            errors.append(".env is tracked by git")
    return errors


GIGSIM_LOCK = ROOT / "gigsim" / ".lock.sha256"


def _digest(p: Path) -> str:
    """SHA-256 of a file; text files are hashed with LF endings so Windows and Linux checkouts
    of the same commit agree."""
    data = p.read_bytes()
    if b"\0" not in data[:8192]:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def freeze_gigsim() -> int:
    root = ROOT / "gigsim"
    files = sorted(
        f
        for f in root.rglob("*")
        if f.is_file() and f != GIGSIM_LOCK and "__pycache__" not in f.parts
    )
    lines = ["# sha256 (text hashed with LF line endings)  path under gigsim/"]
    lines += [f"{_digest(f)}  {f.relative_to(root).as_posix()}" for f in files]
    GIGSIM_LOCK.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"locked {len(files)} files in {GIGSIM_LOCK.relative_to(ROOT).as_posix()}")
    return 0


def check_gigsim_lock() -> list[str]:
    lock = GIGSIM_LOCK
    if not lock.exists():
        return []  # not frozen yet (student-built simulator still evolving)
    expected: dict[str, str] = {}
    for line in lock.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        digest, _, rel = line.partition("  ")
        expected[rel.strip()] = digest.strip()
    errors = []
    for rel, digest in expected.items():
        p = ROOT / "gigsim" / rel
        if not p.exists():
            errors.append(f"gigsim/{rel} missing (locked)")
            continue
        actual = _digest(p)
        if actual != digest:
            errors.append(f"gigsim/{rel} modified (locked by gigsim/.lock.sha256)")
    return errors


PROMPT_HINTS = re.compile(
    r"(you are an? |your task is|respond (only )?(in|with) json|as an ai|system prompt)", re.I
)


def check_prompts_location(files: list[Path]) -> list[str]:
    errors = []
    for f in files:
        rel = f.relative_to(ROOT).as_posix()
        if f.suffix != ".py" or not rel.startswith(
            ("agent/", "mcp_servers/", "apps/api/", "worker/", "rag/")
        ):
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r'("""|\'\'\')(.*?)\1', text, re.S):
            body = m.group(2)
            if len(body) > 300 and PROMPT_HINTS.search(body):
                errors.append(f"prompt-like string in {rel}; move it to agent/prompts/*.md")
                break
    return errors


NUM = re.compile(r"(?<![\w./-])\d+(?:\.\d+)?%?(?![\w./-])")


def check_readme_numbers() -> list[str]:
    readme = ROOT / "README.md"
    if not readme.exists():
        return []
    errors = []
    in_results_block = False
    for i, line in enumerate(readme.read_text(encoding="utf-8").splitlines(), 1):
        if "<!-- results:" in line:
            in_results_block = True
        if "<!-- /results -->" in line:
            in_results_block = False
            continue
        if not line.lstrip().startswith("|"):
            continue  # only table rows are checked
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if all(set(c) <= set("-: ") for c in cells):
            continue
        has_number = any(NUM.search(c) for c in cells[1:])
        cites = "evals/results/" in line or in_results_block
        if has_number and not cites:
            errors.append(f"README.md:{i} table row has numbers without an evals/results/ citation")
    return errors


def main() -> int:
    files = tracked_files()
    errors: list[str] = []
    errors += check_secrets(files)
    errors += check_gigsim_lock()
    errors += check_prompts_location(files)
    errors += check_readme_numbers()
    if errors:
        print("CI policy checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("CI policy checks passed (secrets, gigsim lock, prompts location, README numbers).")
    return 0


if __name__ == "__main__":
    sys.exit(freeze_gigsim() if "--freeze-gigsim" in sys.argv[1:] else main())
