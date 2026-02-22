#!/usr/bin/env python3
"""Job search consolidation tool.

Fetches role-specific listings from multiple public job APIs, deduplicates postings,
ranks company fit, and generates resume-tailoring guidance.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DEFAULT_SITES = ("remotive", "arbeitnow", "remoteok")
COMMON_STOPWORDS = {
    "and",
    "the",
    "for",
    "with",
    "you",
    "your",
    "are",
    "our",
    "from",
    "that",
    "this",
    "will",
    "have",
    "has",
    "not",
    "but",
    "job",
    "role",
    "team",
    "all",
    "who",
    "what",
    "why",
    "can",
    "per",
}


@dataclass
class Job:
    site: str
    id: str
    title: str
    company: str
    location: str
    url: str
    posted_at: str
    tags: list[str]
    description: str


@dataclass
class ScoredJob:
    job: Job
    fit_score: float
    matched_skills: list[str]
    missing_skills: list[str]


def fetch_json(url: str, timeout: int = 20) -> Any:
    req = Request(url, headers={"User-Agent": "JobSearchTool/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def remotive_jobs(role: str, limit: int) -> list[Job]:
    params = urlencode({"search": role})
    payload = fetch_json(f"https://remotive.com/api/remote-jobs?{params}")
    jobs = []
    for item in payload.get("jobs", [])[:limit]:
        jobs.append(
            Job(
                site="remotive",
                id=str(item.get("id", "")),
                title=item.get("title", ""),
                company=item.get("company_name", ""),
                location=item.get("candidate_required_location", "Remote"),
                url=item.get("url", ""),
                posted_at=item.get("publication_date", ""),
                tags=item.get("tags", []) or [],
                description=strip_html(item.get("description", "")),
            )
        )
    return jobs


def arbeitnow_jobs(role: str, limit: int) -> list[Job]:
    payload = fetch_json("https://www.arbeitnow.com/api/job-board-api")
    jobs = []
    pattern = re.compile(re.escape(role), re.IGNORECASE)
    for item in payload.get("data", []):
        title = item.get("title", "")
        description = strip_html(item.get("description", ""))
        if not (pattern.search(title) or pattern.search(description)):
            continue
        jobs.append(
            Job(
                site="arbeitnow",
                id=str(item.get("slug", "")),
                title=title,
                company=item.get("company_name", ""),
                location=item.get("location", ""),
                url=item.get("url", ""),
                posted_at=item.get("created_at", ""),
                tags=item.get("tags", []) or [],
                description=description,
            )
        )
        if len(jobs) >= limit:
            break
    return jobs


def remoteok_jobs(role: str, limit: int) -> list[Job]:
    payload = fetch_json("https://remoteok.com/api")
    jobs = []
    pattern = re.compile(re.escape(role), re.IGNORECASE)
    for item in payload[1:]:  # first row is metadata
        title = item.get("position", "")
        description = strip_html(item.get("description", ""))
        if not (pattern.search(title) or pattern.search(description)):
            continue
        tags = [t for t in item.get("tags", []) if isinstance(t, str)]
        jobs.append(
            Job(
                site="remoteok",
                id=str(item.get("id", "")),
                title=title,
                company=item.get("company", ""),
                location=item.get("location", "Remote"),
                url=item.get("url", ""),
                posted_at=str(item.get("date", "")),
                tags=tags,
                description=description,
            )
        )
        if len(jobs) >= limit:
            break
    return jobs


def strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_key(job: Job) -> str:
    title = re.sub(r"[^a-z0-9]+", "", job.title.lower())
    company = re.sub(r"[^a-z0-9]+", "", job.company.lower())
    return f"{title}:{company}"


def deduplicate_jobs(jobs: list[Job]) -> list[Job]:
    merged: dict[str, Job] = {}
    for job in jobs:
        key = normalize_key(job)
        existing = merged.get(key)
        if not existing:
            merged[key] = job
            continue

        if len(job.description) > len(existing.description):
            merged[key] = job
        elif len(job.tags) > len(existing.tags):
            merged[key] = job
    return list(merged.values())


def extract_keywords(text: str, max_count: int = 30) -> list[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9+#.\-]{2,}", text.lower())
    filtered = [w for w in words if w not in COMMON_STOPWORDS and not w.isdigit()]
    counts = Counter(filtered)
    return [w for w, _ in counts.most_common(max_count)]


def score_jobs(
    jobs: list[Job], desired_skills: list[str], preferred_location: str | None = None
) -> list[ScoredJob]:
    normalized_skills = [s.strip().lower() for s in desired_skills if s.strip()]
    scored: list[ScoredJob] = []

    for job in jobs:
        haystack = f"{job.title} {' '.join(job.tags)} {job.description}".lower()
        matched = [s for s in normalized_skills if s in haystack]
        missing = [s for s in normalized_skills if s not in haystack]

        skill_component = (len(matched) / max(1, len(normalized_skills))) * 70
        tag_component = min(20, len(job.tags) * 2)
        location_component = 0
        if preferred_location:
            if preferred_location.lower() in (job.location or "").lower():
                location_component = 10

        fit_score = round(skill_component + tag_component + location_component, 2)
        scored.append(ScoredJob(job=job, fit_score=fit_score, matched_skills=matched, missing_skills=missing))

    return sorted(scored, key=lambda j: j.fit_score, reverse=True)


def company_rankings(scored_jobs: list[ScoredJob]) -> list[dict[str, Any]]:
    company_stats: dict[str, list[float]] = defaultdict(list)
    for sj in scored_jobs:
        company_stats[sj.job.company].append(sj.fit_score)

    ranked = []
    for company, scores in company_stats.items():
        ranked.append(
            {
                "company": company,
                "openings": len(scores),
                "avg_fit_score": round(sum(scores) / len(scores), 2),
                "max_fit_score": max(scores),
            }
        )
    return sorted(ranked, key=lambda x: (x["avg_fit_score"], x["openings"]), reverse=True)


def resume_guidance(scored_jobs: list[ScoredJob], resume_text: str) -> dict[str, Any]:
    top_jobs = scored_jobs[:20]
    market_keywords = Counter()
    missing = Counter()
    for sj in top_jobs:
        market_keywords.update(sj.job.tags)
        market_keywords.update(extract_keywords(sj.job.title, 10))
        market_keywords.update(extract_keywords(sj.job.description, 20))
        missing.update(sj.missing_skills)

    resume_keywords = set(extract_keywords(resume_text, 200))
    top_market = [k for k, _ in market_keywords.most_common(30)]
    missing_from_resume = [k for k in top_market if k.lower() not in resume_keywords]

    return {
        "top_market_keywords": top_market,
        "skills_most_often_missing": [k for k, _ in missing.most_common(15)],
        "resume_gap_keywords": missing_from_resume[:20],
    }


def write_csv(scored_jobs: list[ScoredJob], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "fit_score",
                "site",
                "company",
                "title",
                "location",
                "posted_at",
                "url",
                "matched_skills",
                "missing_skills",
            ]
        )
        for sj in scored_jobs:
            writer.writerow(
                [
                    sj.fit_score,
                    sj.job.site,
                    sj.job.company,
                    sj.job.title,
                    sj.job.location,
                    sj.job.posted_at,
                    sj.job.url,
                    ";".join(sj.matched_skills),
                    ";".join(sj.missing_skills),
                ]
            )


def write_report(
    role: str,
    sites: list[str],
    scored_jobs: list[ScoredJob],
    rankings: list[dict[str, Any]],
    guidance: dict[str, Any],
    output: Path,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Job Search Consolidation Report - {role}",
        "",
        f"Generated: {dt.datetime.now().isoformat(timespec='seconds')}",
        f"Sources: {', '.join(sites)}",
        f"Unique listings: {len(scored_jobs)}",
        "",
        "## Top Companies to Target",
        "",
        "| Company | Openings | Avg Fit | Best Fit |",
        "|---|---:|---:|---:|",
    ]
    for row in rankings[:20]:
        lines.append(
            f"| {row['company']} | {row['openings']} | {row['avg_fit_score']} | {row['max_fit_score']} |"
        )

    lines += ["", "## Best Matching Jobs", "", "| Fit | Company | Title | Site | Location | Link |", "|---:|---|---|---|---|---|"]
    for sj in scored_jobs[:30]:
        lines.append(
            f"| {sj.fit_score} | {sj.job.company} | {sj.job.title} | {sj.job.site} | {sj.job.location} | [apply]({sj.job.url}) |"
        )

    lines += [
        "",
        "## Resume Tailoring Checklist",
        "",
        "### High-value keywords from market",
        ", ".join(guidance["top_market_keywords"][:20]),
        "",
        "### Desired skills most often missing in postings",
        ", ".join(guidance["skills_most_often_missing"][:20]) or "None",
        "",
        "### Keywords likely missing from your resume",
        ", ".join(guidance["resume_gap_keywords"][:20]) or "None",
        "",
        "### Suggested workflow to reduce admin time",
        "1. Focus outreach on the top 10 companies by average fit score.",
        "2. Tailor one resume master version using the keyword checklist above.",
        "3. Batch applications by company so each customization is reused across similar roles.",
        "4. Re-run this tool every 2-3 days and only review newly surfaced companies/jobs.",
    ]

    output.write_text("\n".join(lines), encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    sites = [s.strip().lower() for s in args.sites.split(",") if s.strip()]
    unknown_sites = [s for s in sites if s not in DEFAULT_SITES]
    if unknown_sites:
        print(f"Unsupported sites: {unknown_sites}. Supported: {DEFAULT_SITES}", file=sys.stderr)
        return 2

    all_jobs: list[Job] = []
    failures = []
    for site in sites:
        try:
            if site == "remotive":
                all_jobs.extend(remotive_jobs(args.role, args.per_site_limit))
            elif site == "arbeitnow":
                all_jobs.extend(arbeitnow_jobs(args.role, args.per_site_limit))
            elif site == "remoteok":
                all_jobs.extend(remoteok_jobs(args.role, args.per_site_limit))
        except URLError as exc:
            failures.append(f"{site}: {exc}")

    if failures:
        print("Some sources failed:", *failures, sep="\n- ", file=sys.stderr)

    deduped = deduplicate_jobs(all_jobs)
    desired_skills = [s.strip() for s in args.skills.split(",") if s.strip()]
    scored = score_jobs(deduped, desired_skills, args.location)

    resume_text = ""
    if args.resume and Path(args.resume).exists():
        resume_text = Path(args.resume).read_text(encoding="utf-8", errors="ignore")

    rankings = company_rankings(scored)
    guidance = resume_guidance(scored, resume_text)

    write_csv(scored, Path(args.out_csv))
    write_report(args.role, sites, scored, rankings, guidance, Path(args.out_report))

    print(f"Collected {len(all_jobs)} jobs, reduced to {len(deduped)} unique postings.")
    print(f"Wrote ranked listings to {args.out_csv}")
    print(f"Wrote strategy report to {args.out_report}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Consolidate job listings and rank company fit.")
    p.add_argument("role", help="Target role (e.g., 'Data Scientist')")
    p.add_argument(
        "--skills",
        default="python,sql,communication,leadership",
        help="Comma-separated skills used to score fit.",
    )
    p.add_argument("--location", default=None, help="Preferred location keyword (optional).")
    p.add_argument("--resume", default=None, help="Path to resume text/markdown for gap analysis.")
    p.add_argument("--sites", default=",".join(DEFAULT_SITES), help="Comma-separated sites to include.")
    p.add_argument("--per-site-limit", type=int, default=120, help="Max listings fetched per source.")
    p.add_argument("--out-csv", default="output/job_matches.csv", help="Output CSV path.")
    p.add_argument("--out-report", default="output/job_report.md", help="Output markdown report path.")
    return p


if __name__ == "__main__":
    parser = build_parser()
    raise SystemExit(run(parser.parse_args()))
