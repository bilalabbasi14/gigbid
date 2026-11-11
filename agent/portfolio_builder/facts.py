"""Deterministic code facts: what a repository verifiably contains. Every claim in a generated case
study must cite one of these, so "verified against the code" means verified against this list.

Facts come from the file tree (languages, tests, CI, containers), dependency manifests (libraries,
mapped to frameworks), imports in sampled source files, the README (the author's own statements,
marked as such) and commit history when available.
"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from collections import Counter
from typing import Any

from pydantic import BaseModel

from agent.portfolio_builder.sources import RepoRef, RepoSource

LANG = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".sql": "SQL",
    ".ipynb": "Jupyter notebooks",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".rb": "Ruby",
    ".php": "PHP",
    ".r": "R",
    ".scala": "Scala",
    ".cs": "C#",
    ".kt": "Kotlin",
    ".swift": "Swift",
    ".dart": "Dart",
    ".vue": "Vue",
    ".dax": "DAX",
}
MANIFESTS = [
    "requirements.txt",
    "pyproject.toml",
    "package.json",
    "environment.yml",
    "Pipfile",
    "setup.py",
    "go.mod",
    "Cargo.toml",
    "pom.xml",
    "composer.json",
    "Gemfile",
]
FRAMEWORKS = {
    "fastapi": "FastAPI",
    "django": "Django",
    "djangorestframework": "Django REST Framework",
    "flask": "Flask",
    "langchain": "LangChain",
    "langgraph": "LangGraph",
    "llama-index": "LlamaIndex",
    "llama_index": "LlamaIndex",
    "torch": "PyTorch",
    "pytorch": "PyTorch",
    "tensorflow": "TensorFlow",
    "keras": "Keras",
    "scikit-learn": "scikit-learn",
    "sklearn": "scikit-learn",
    "xgboost": "XGBoost",
    "lightgbm": "LightGBM",
    "pandas": "pandas",
    "numpy": "NumPy",
    "polars": "Polars",
    "transformers": "Hugging Face Transformers",
    "sentence-transformers": "sentence-transformers",
    "openai": "OpenAI API",
    "anthropic": "Anthropic API",
    "pgvector": "pgvector",
    "psycopg": "PostgreSQL",
    "psycopg2": "PostgreSQL",
    "psycopg2-binary": "PostgreSQL",
    "asyncpg": "PostgreSQL",
    "sqlalchemy": "SQLAlchemy",
    "pymongo": "MongoDB",
    "mongoose": "MongoDB",
    "redis": "Redis",
    "celery": "Celery",
    "apache-airflow": "Airflow",
    "airflow": "Airflow",
    "dbt-core": "dbt",
    "dbt": "dbt",
    "mlflow": "MLflow",
    "opencv-python": "OpenCV",
    "cv2": "OpenCV",
    "spacy": "spaCy",
    "nltk": "NLTK",
    "boto3": "AWS SDK",
    "sagemaker": "AWS SageMaker",
    "google-cloud-bigquery": "BigQuery",
    "snowflake-connector-python": "Snowflake",
    "streamlit": "Streamlit",
    "plotly": "Plotly",
    "matplotlib": "Matplotlib",
    "pytest": "pytest",
    "react": "React",
    "next": "Next.js",
    "vue": "Vue",
    "@angular/core": "Angular",
    "express": "Express",
    "prisma": "Prisma",
    "@prisma/client": "Prisma",
    "tailwindcss": "Tailwind CSS",
    "stripe": "Stripe",
    "@supabase/supabase-js": "Supabase",
    "firebase": "Firebase",
    "graphql": "GraphQL",
    "@apollo/client": "Apollo GraphQL",
    "jest": "Jest",
    "vitest": "Vitest",
    "@playwright/test": "Playwright",
    "typescript": "TypeScript",
    "socket.io": "Socket.IO",
    "chromadb": "Chroma",
    "pinecone-client": "Pinecone",
    "faiss-cpu": "FAISS",
    "qdrant-client": "Qdrant",
    "uvicorn": "Uvicorn",
    "pydantic": "Pydantic",
}
SOURCE_PRIORITY = re.compile(
    r"(^|/)(main|app|server|index|api|pipeline|train|model|retriever|ingest|etl|handler|routes?|views?|service)\.(py|ts|tsx|js)$",
    re.I,
)


class Fact(BaseModel):
    fact_id: str
    kind: str  # language | dependency | framework | tests | ci | container | readme | structure | commits | import
    text: str
    source: str

    def as_evidence(self, repo: str) -> dict[str, Any]:
        return {
            "evidence_id": self.fact_id,
            "title": f"{repo}: {self.kind}",
            "type": "code_fact",
            "excerpt": self.text,
            "source": self.source,
            "project_id": None,
            "year": None,
            "outcome": None,
            "score": 1.0,
        }


def _fid(repo: str, kind: str, text: str) -> str:
    return hashlib.sha1(f"{repo}|{kind}|{text}".encode(), usedforsecurity=False).hexdigest()[:12]


def _deps_from(name: str, text: str) -> list[str]:
    deps: list[str] = []
    try:
        if name == "requirements.txt" or name == "Pipfile":
            for ln in text.splitlines():
                ln = ln.split("#")[0].strip()
                if ln and not ln.startswith(("-", "[")):
                    deps.append(re.split(r"[<>=!~\[; ]", ln)[0])
        elif name == "pyproject.toml":
            data = tomllib.loads(text)
            for d in data.get("project", {}).get("dependencies", []) + list(
                (data.get("tool", {}).get("poetry", {}).get("dependencies", {}) or {}).keys()
            ):
                deps.append(re.split(r"[<>=!~\[; ]", d)[0])
        elif name == "package.json":
            data = json.loads(text)
            deps += list((data.get("dependencies") or {}).keys()) + list(
                (data.get("devDependencies") or {}).keys()
            )
        elif name == "environment.yml":
            for ln in text.splitlines():
                m = re.match(r"\s*-\s*([A-Za-z0-9_.\-]+)", ln)
                if m:
                    deps.append(m.group(1))
    except (ValueError, tomllib.TOMLDecodeError):
        pass
    return [d.lower() for d in deps if d and d.lower() not in ("python", "pip")]


def _imports(path: str, text: str) -> set[str]:
    mods: set[str] = set()
    if path.endswith(".py"):
        for m in re.finditer(r"^\s*(?:from|import)\s+([A-Za-z_][\w]*)", text, re.M):
            mods.add(m.group(1).lower())
    elif re.search(r"\.(ts|tsx|js|jsx)$", path):
        for m in re.finditer(r"""(?:from|require\()\s*['"]([@\w][\w\-./@]*)['"]""", text):
            mod = m.group(1)
            if not mod.startswith("."):
                mods.add("/".join(mod.split("/")[:2]) if mod.startswith("@") else mod.split("/")[0])
    return mods


async def extract_facts(
    source: RepoSource, repo: RepoRef, max_files: int = 6
) -> tuple[list[Fact], dict[str, Any]]:
    """Return facts plus a profile (skills, libraries, files read) for metadata."""
    name = repo.name
    tree = await source.tree(name)
    facts: list[Fact] = []

    def add(kind: str, text: str, src: str) -> None:
        f = Fact(fact_id=_fid(name, kind, text), kind=kind, text=text, source=src)
        if all(x.fact_id != f.fact_id for x in facts):
            facts.append(f)

    exts = Counter(
        LANG[ext]
        for p in tree
        if (ext := ("." + p.rsplit(".", 1)[-1].lower()) if "." in p else "") in LANG
    )
    for lang, n in exts.most_common(4):
        add("language", f"{n} {lang} file{'s' if n > 1 else ''} in the repository", "file tree")
    add(
        "structure",
        f"{len(tree)} files in total; top-level entries: {', '.join(sorted({p.split('/')[0] for p in tree})[:12])}",
        "file tree",
    )
    tests = [
        p
        for p in tree
        if re.search(
            r"(^|/)(tests?|__tests__|spec)/|(^|/)test_[^/]+\.py$|\.(test|spec)\.(ts|tsx|js)$", p
        )
    ]
    if tests:
        add(
            "tests", f"automated tests present ({len(tests)} test files, e.g. {tests[0]})", tests[0]
        )
    ci = [
        p
        for p in tree
        if p.startswith(".github/workflows/") or p in (".gitlab-ci.yml", ".circleci/config.yml")
    ]
    if ci:
        add("ci", f"continuous integration configured ({', '.join(ci[:2])})", ci[0])
    docker = [
        p
        for p in tree
        if p.split("/")[-1]
        in ("Dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yaml")
    ]
    if docker:
        add(
            "container",
            f"containerised with {', '.join(sorted({p.split('/')[-1] for p in docker}))}",
            docker[0],
        )
    notebooks = [p for p in tree if p.endswith(".ipynb")]
    if notebooks:
        add("structure", f"{len(notebooks)} Jupyter notebook(s), e.g. {notebooks[0]}", notebooks[0])

    libraries: set[str] = set()
    for man in [p for p in tree if p.split("/")[-1] in MANIFESTS][:4]:
        text = await source.read(name, man) or ""
        deps = _deps_from(man.split("/")[-1], text)
        if deps:
            add("dependency", f"{man} declares: {', '.join(sorted(set(deps))[:25])}", man)
            for d in deps:
                if d in FRAMEWORKS:
                    libraries.add(FRAMEWORKS[d])
                    add("framework", f"uses {FRAMEWORKS[d]} (declared in {man})", man)

    sources = [
        p
        for p in tree
        if re.search(r"\.(py|ts|tsx|js|jsx|sql)$", p)
        and not re.search(r"(^|/)(tests?|__tests__)/|\.d\.ts$|config\.(js|ts)$", p)
    ]
    sources.sort(key=lambda p: (0 if SOURCE_PRIORITY.search(p) else 1, p.count("/"), p))
    read_files = []
    for path in sources[:max_files]:
        text = await source.read(name, path, max_chars=8000)
        if not text:
            continue
        read_files.append(path)
        mods = _imports(path, text)
        known = sorted({FRAMEWORKS[m] for m in mods if m in FRAMEWORKS})
        if known:
            add("import", f"{path} imports {', '.join(known)}", path)
            libraries.update(known)
        defs = re.findall(
            r"^(?:async\s+)?def\s+(\w+)|^class\s+(\w+)|^export\s+(?:default\s+)?(?:async\s+)?function\s+(\w+)",
            text,
            re.M,
        )
        names = [next(x for x in d if x) for d in defs][:6]
        if names:
            add("structure", f"{path} defines {', '.join(names)}", path)

    readme_path = next(
        (p for p in tree if p.lower() in ("readme.md", "readme.rst", "readme.txt")), None
    )
    if readme_path:
        readme = await source.read(name, readme_path, max_chars=6000) or ""
        paras = [
            p.strip()
            for p in re.split(r"\n\s*\n", re.sub(r"```.*?```", "", readme, flags=re.S))
            if p.strip() and not p.strip().startswith(("#", "![", "[!", "<"))
        ]
        for p in paras[:4]:
            add(
                "readme",
                f"README (author's statement): {re.sub(r'\s+', ' ', p)[:400]}",
                readme_path,
            )
    elif repo.description:
        add(
            "readme",
            f"repository description (author's statement): {repo.description}",
            "repository metadata",
        )

    commits = await source.commits(name)
    if commits.count:
        add(
            "commits",
            f"{commits.count}{'+' if commits.count >= 100 else ''} commits between {commits.first[:10] if commits.first else '?'} and {commits.last[:10] if commits.last else '?'}",
            "commit history",
        )

    profile = {
        "languages": [lang for lang, _ in exts.most_common(4)],
        "libraries": sorted(libraries),
        "has_tests": bool(tests),
        "has_ci": bool(ci),
        "has_docker": bool(docker),
        "files_read": read_files,
        "file_count": len(tree),
        "year": int(commits.last[:4]) if commits.last else None,
        "commits": commits.count,
    }
    return facts, profile
