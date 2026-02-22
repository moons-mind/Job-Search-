# Job Search Consolidation Tool

A practical CLI tool that reduces job-search admin time by:

1. Pulling role-specific listings from multiple public job boards.
2. Deduplicating overlapping postings.
3. Ranking opportunities by fit against your target skills/location.
4. Highlighting top companies worth focused effort.
5. Generating a resume-tailoring checklist from current market demand.

## Data Sources

- Remotive API
- Arbeitnow API
- RemoteOK API

> Note: LinkedIn/Indeed/Glassdoor APIs are not openly available for anonymous access, so this tool uses public APIs and is designed to be extendable.

## Quick start

```bash
python3 job_search_tool.py "Product Manager" \
  --skills "product strategy,roadmap,analytics,stakeholder management" \
  --location "United States" \
  --resume my_resume.md
```

### Outputs

- `output/job_matches.csv`: ranked and deduped job list.
- `output/job_report.md`: company prioritization + resume checklist.

## Useful options

- `--sites remotive,arbeitnow,remoteok`
- `--per-site-limit 100`
- `--out-csv output/my_jobs.csv`
- `--out-report output/my_report.md`

## How this minimizes wasted effort

- Creates a **single backlog** of ranked jobs instead of site-by-site searching.
- Surfaces **best-fit companies first** via score + opening count.
- Generates a **resume keyword checklist** based on current postings.
- Encourages **batch tailoring** by targeting similar companies/roles together.
