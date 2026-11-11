"""Build the GigSim job pool from two public Kaggle Upwork datasets.

Inputs (git-ignored, downloaded with `kaggle datasets download`):
  data/raw/kaggle/upwork50k/upwork-jobs.csv            (asaniczka, ODC-By)
  data/raw/kaggle/upwork60k/Final_Upwork_Dataset.csv   (ahmedmyalo, Apache-2.0)

Output (committed, compressed, attributed in docs/DATA_CARD.md):
  gigsim/seed/jobs.jsonl.gz        unified real job posts for the three personas
  gigsim/seed/market_stats.json    price statistics per persona and payment type

Run: uv run python -m data.scripts.prepare_jobs [--per-persona 700] [--seed 42]
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import html
import json
import random
import re
import statistics
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW50 = ROOT / "data/raw/kaggle/upwork50k/upwork-jobs.csv"
RAW60 = ROOT / "data/raw/kaggle/upwork60k/Final_Upwork_Dataset.csv"
OUT_DIR = ROOT / "gigsim/seed"

PERSONAS = ("ai_ml", "fullstack", "data_analyst")

# Keyword signals -> persona category. Order matters: ML beats analyst beats fullstack when tied.
SIGNALS: dict[str, list[str]] = {
    "ai_ml": [
        "machine learning",
        "deep learning",
        "neural",
        "llm",
        "large language",
        "nlp",
        "natural language",
        "computer vision",
        "pytorch",
        "tensorflow",
        "keras",
        "hugging face",
        "huggingface",
        "transformer",
        "openai",
        "gpt",
        "langchain",
        "rag",
        "chatbot",
        "fine-tun",
        "finetun",
        "embedding",
        "classification model",
        "prediction model",
        "predictive model",
        "scikit",
        "sklearn",
        "xgboost",
        "generative ai",
        "ai model",
        "ai agent",
        "stable diffusion",
        "yolo",
        "object detection",
        "speech recognition",
        "recommendation system",
        "ml engineer",
        "data scientist",
        "data science",
    ],
    "data_analyst": [
        "data analy",
        "power bi",
        "powerbi",
        "tableau",
        "looker",
        "excel",
        "google sheets",
        "spreadsheet",
        "dashboard",
        "sql",
        "data visualization",
        "data visualisation",
        "etl",
        "data cleaning",
        "statistic",
        "pandas",
        "reporting",
        "kpi",
        "bigquery",
        "snowflake",
        "google analytics",
        "data entry",
        "pivot",
        "vba",
        "dbt",
        "data pipeline",
    ],
    "fullstack": [
        "react",
        "next.js",
        "nextjs",
        "node",
        "express",
        "django",
        "flask",
        "fastapi",
        "full stack",
        "full-stack",
        "fullstack",
        "web app",
        "web application",
        "rest api",
        "api integration",
        "typescript",
        "javascript",
        "vue",
        "angular",
        "laravel",
        "php",
        "postgres",
        "mongodb",
        "mysql",
        "saas",
        "backend",
        "frontend",
        "front-end",
        "back-end",
        "tailwind",
        "supabase",
        "firebase",
        "stripe integration",
        "web developer",
        "mern",
        "graphql",
        "docker",
    ],
}
EXCLUDE = [
    "wordpress theme",
    "elementor",
    "shopify theme",
    "wix",
    "squarespace",
    "3d",
    "logo",
    "video edit",
]

APPLICANT_BUCKETS = {
    "Less than 5": (0, 4),
    "5 to 10": (5, 10),
    "10 to 15": (10, 15),
    "15 to 20": (15, 20),
    "20 to 50": (20, 50),
    "50+": (50, 90),
}


def norm_text(s: Any) -> str:
    if not isinstance(s, str):
        return ""
    s = html.unescape(s).replace("\r", "\n")
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def money(v: Any) -> float | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, int | float):
        return float(v)
    m = re.search(r"[\d,]+(?:\.\d+)?", str(v))
    return float(m.group().replace(",", "")) if m else None


def classify(text: str) -> tuple[str | None, int]:
    t = text.lower()
    if any(x in t for x in EXCLUDE):
        return None, 0
    scores = {p: sum(1 for kw in kws if kw in t) for p, kws in SIGNALS.items()}
    best = max(scores, key=lambda p: (scores[p], -PERSONAS.index(p)))
    return (best, scores[best]) if scores[best] >= 2 else (None, scores[best])


def split_50k_description(desc: str) -> tuple[str, list[str], str | None]:
    """The 50k rows embed 'Budget: ... Posted On: ... Category: ... Skills: ...' in the text."""
    skills: list[str] = []
    category = None
    m = re.search(r"Skills:(.*)$", desc, re.S)
    if m:
        raw = m.group(1)
        raw = re.split(r"Skills:", raw)[0]
        skills = [s.strip() for s in raw.split(",") if s.strip()]
        desc = desc[: m.start()]
    m = re.search(r"Category:\s*([^\n]+?)(?:Skills:|$)", desc)
    if m:
        category = m.group(1).strip()
        desc = desc[: m.start()]
    desc = re.split(r"(?:Hourly Range|Budget):\s*\$", desc)[0]
    desc = re.split(r"Posted On:", desc)[0]
    return desc.strip(), skills[:15], category


def job_from_50k(r: pd.Series) -> dict[str, Any] | None:
    desc, skills, category = split_50k_description(norm_text(r["description"]))
    if len(desc) < 120:
        return None
    hourly = str(r.get("is_hourly")).lower() == "true"
    return {
        "source": "kaggle:asaniczka/upwork-job-postings-dataset-2024-50k-records",
        "title": norm_text(r["title"])[:160],
        "description": desc[:4000],
        "skills": skills,
        "category": category,
        "payment_type": "hourly" if hourly else "fixed",
        "hourly_min": money(r.get("hourly_low")) if hourly else None,
        "hourly_max": money(r.get("hourly_high")) if hourly else None,
        "budget": money(r.get("budget")) if not hourly else None,
        "experience_level": None,
        "duration": None,
        "posted_at": norm_text(r.get("published_date"))[:10] or None,
        "client": {
            "country": norm_text(r.get("country")) or None,
            "payment_verified": None,
            "total_spent": None,
            "rating": None,
            "reviews_count": None,
        },
        "applicants": None,
        "connects_cost": None,
    }


def job_from_60k(r: pd.Series) -> dict[str, Any] | None:
    desc = norm_text(r["Description"])
    if len(desc) < 120:
        return None
    cats = [norm_text(r.get(f"Category_{i}")) for i in range(1, 10)]
    skills = [c for c in cats if c]
    hourly = str(r.get("Payment_type")).lower().startswith("hour")
    lo, hi = None, None
    if hourly:
        lo, hi = money(r.get("Start_rate")), money(r.get("End_rate"))
        if lo == 0:
            lo = None
        if not lo and not hi:
            lo = money(r.get("Hourly_Rate"))
    rating = money(r.get("Rating"))
    bucket = APPLICANT_BUCKETS.get(str(r.get("Applicants_Num")))
    connects = money(r.get("Connects_Num"))
    return {
        "source": "kaggle:ahmedmyalo/upwork-freelance-jobs-60k",
        "title": norm_text(r["Job Title"])[:160],
        "description": desc[:4000],
        "skills": skills[:15],
        "category": skills[0] if skills else None,
        "payment_type": "hourly" if hourly else "fixed",
        "hourly_min": lo,
        "hourly_max": hi,
        "budget": money(r.get("Job_Cost")) if not hourly else None,
        "experience_level": norm_text(r.get("EX_level_demand")) or None,
        "duration": norm_text(r.get("Time_Limitation")) or None,
        "posted_at": None,
        "client": {
            "country": norm_text(r.get("Client_Country")) or None,
            "payment_verified": str(r.get("Payment_Situation"))
            .lower()
            .startswith("payment verified"),
            "total_spent": money(r.get("Spent($)")),
            "rating": rating if rating and rating > 0 else None,
            "reviews_count": int(money(r.get("Feedback_Num")) or 0),
        },
        "applicants": bucket,
        "connects_cost": int(connects) if connects else None,
    }


def fingerprint(job: dict[str, Any]) -> str:
    key = re.sub(r"\W+", " ", (job["title"] + " " + job["description"][:300]).lower())
    return hashlib.sha1(key.encode(), usedforsecurity=False).hexdigest()[:16]


def sane_price(job: dict[str, Any]) -> bool:
    if job["payment_type"] == "fixed":
        b = job["budget"]
        return b is None or 20 <= b <= 50_000
    lo, hi = job["hourly_min"], job["hourly_max"]
    return (lo is None or 3 <= lo <= 300) and (hi is None or 3 <= hi <= 500)


def build(per_persona: int, seed: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rng = random.Random(seed)
    frames = [
        (pd.read_csv(RAW50), job_from_50k),
        (pd.read_csv(RAW60, low_memory=False), job_from_60k),
    ]
    seen: set[str] = set()
    by_persona: dict[str, list[dict[str, Any]]] = {p: [] for p in PERSONAS}
    for df, fn in frames:
        for _, row in df.iterrows():
            job = fn(row)
            if not job or not sane_price(job):
                continue
            persona, score = classify(
                job["title"] + " " + " ".join(job["skills"]) + " " + job["description"]
            )
            if not persona:
                continue
            fp = fingerprint(job)
            if fp in seen:
                continue
            seen.add(fp)
            job["persona"] = persona
            job["signal_score"] = score
            job["job_id"] = f"job_{fp}"
            by_persona[persona].append(job)

    jobs: list[dict[str, Any]] = []
    for p in PERSONAS:
        pool = by_persona[p]
        pool.sort(key=lambda j: (-j["signal_score"], j["job_id"]))
        top = pool[: per_persona * 3]  # keep the clearly on-topic ones, then sample for variety
        rng.shuffle(top)
        jobs.extend(top[:per_persona])
    rng.shuffle(jobs)

    stats: dict[str, Any] = {"generated_from": [str(RAW50.name), str(RAW60.name)], "personas": {}}
    for p in PERSONAS:
        pj = [j for j in jobs if j["persona"] == p]
        fixed = [j["budget"] for j in pj if j["payment_type"] == "fixed" and j["budget"]]
        hourly = [j["hourly_min"] for j in pj if j["payment_type"] == "hourly" and j["hourly_min"]]
        hourly_hi = [
            j["hourly_max"] for j in pj if j["payment_type"] == "hourly" and j["hourly_max"]
        ]

        def q(xs: list[float]) -> dict[str, float] | None:
            if len(xs) < 5:
                return None
            qs = statistics.quantiles(xs, n=20)
            return {
                "n": len(xs),
                "p10": qs[1],
                "p25": qs[4],
                "p50": qs[9],
                "p75": qs[14],
                "p90": qs[17],
            }

        stats["personas"][p] = {
            "jobs": len(pj),
            "fixed_budget_usd": q(fixed),
            "hourly_min_usd": q(hourly),
            "hourly_max_usd": q(hourly_hi),
            "share_hourly": round(
                sum(1 for j in pj if j["payment_type"] == "hourly") / max(1, len(pj)), 3
            ),
            "connects_cost_mode": statistics.mode(
                [j["connects_cost"] for j in pj if j["connects_cost"]] or [8]
            ),
        }
    return jobs, stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-persona", type=int, default=700)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    jobs, stats = build(args.per_persona, args.seed)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT_DIR / "jobs.jsonl.gz", "wt", encoding="utf-8") as f:
        for j in jobs:
            f.write(json.dumps(j, ensure_ascii=False) + "\n")
    (OUT_DIR / "market_stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    print(f"wrote {len(jobs)} jobs -> {OUT_DIR / 'jobs.jsonl.gz'}")
    for p, s in stats["personas"].items():
        print(
            f"  {p:13s} jobs={s['jobs']:4d} hourly_share={s['share_hourly']}  fixed_p50={s['fixed_budget_usd'] and s['fixed_budget_usd']['p50']}  hourly_p50={s['hourly_min_usd'] and s['hourly_min_usd']['p50']}"
        )


if __name__ == "__main__":
    main()
