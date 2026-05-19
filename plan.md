# RSS AI News Digest — Project Plan

## Overview

A Python CLI script that fetches multiple RSS feeds, uses GitHub Models (gpt-4o-mini for AI relevance filtering, gpt-4o for summarization) to keep only AI-related articles, strips HTML from Techmeme summaries, sorts with Techmeme last, generates a styled local HTML digest, and auto-opens it in the browser. Processed articles are cached to avoid redundant API calls.

---

## Resolved Decisions

| Decision | Choice |
|---|---|
| Feed list input | `feeds.txt` — one URL per line, `#` = comment, manually curated |
| Source detection | URL auto-detected by `"techmeme.com" in url` |
| GitHub Token | `.env` file (`GITHUB_TOKEN=...`), loaded via `python-dotenv`; never hardcoded |
| AI filter model | `gpt-4o-mini` (batch, single API call for all techmeme articles title) |
| AI summary model | `gpt-4o` (per-article) |
| Rate limiting | `time.sleep(0.5)` after each `generate_summary` call |
| HTML language | All English |
| HTML auto-open | `webbrowser.open()` after writing `output.html` |
| Caching | `cache.json` — stores `{url: {is_ai_related, ai_summary}}` |
| Output path | `Path(__file__).parent / "output.html"` (never cwd-relative) |

---

## File Structure

```
RSS_project/
├── main.py              # entry point & pipeline orchestrator
├── models.py            # Article dataclass
├── rss_fetcher.py       # fetch & parse RSS feeds
├── ai_processor.py      # GitHub Models API calls
├── html_generator.py    # Jinja2 HTML generation
├── cache.py             # cache.json read/write
├── feeds.txt            # RSS URLs (manually curated, one per line)
├── .env                 # GITHUB_TOKEN=... (gitignored)
├── cache.json           # auto-generated (gitignored)
├── output.html          # auto-generated (gitignored)
├── requirements.txt
└── Dockerfile
```

---

## Data Model (`models.py`)

```python
@dataclass
class Article:
    title: str
    url: str
    raw_summary: str        # original, may contain HTML
    clean_summary: str      # HTML-stripped plain text
    published: datetime     # timezone-aware UTC
    source_feed: str        # which feed URL it came from
    is_techmeme: bool
    is_ai_related: bool | None   # None = not yet processed
    ai_summary: str | None       # None = not yet processed
```

---

## Dependencies (`requirements.txt`)

| Package | Purpose |
|---|---|
| `feedparser` | Parse RSS/Atom feeds |
| `openai` | GitHub Models API (OpenAI-compatible endpoint) |
| `beautifulsoup4` | Strip HTML tags from Techmeme summaries |
| `lxml` | HTML parser backend for BeautifulSoup (fast, tolerant of malformed HTML) |
| `jinja2` | HTML template rendering with `autoescape=True` (XSS prevention) |
| `python-dotenv` | Load `GITHUB_TOKEN` from `.env` file |

---

## Sprint 1 — Foundation & Data Pipeline

**Goal**: Fetch RSS data, parse into structured objects, establish security boundaries.

| # | Task | File | Security/Quality |
|---|---|---|---|
| 1 | Update `requirements.txt` | `requirements.txt` | |
| 2 | Create `feeds.txt` placeholder + `.gitignore` (exclude `.env`, `cache.json`, `output.html`) | new files | |
| 3 | `Article` dataclass with `published: datetime` (timezone-aware) | `models.py` | [MEDIUM] datetime timezone |
| 4 | `cache.py`: `load_cache()` catches `json.JSONDecodeError`, returns empty dict + warning | `cache.py` | [LOW] cache corruption |
| 5 | `rss_fetcher.py`: URL validation — scheme must be `http`/`https`, reject private IP ranges (`10.x`, `192.168.x`, `172.16-31.x`, `127.x`, `169.254.x`) | `rss_fetcher.py` | [HIGH] SSRF |
| 6 | `rss_fetcher.py`: `fetch_feed()` checks `result.bozo`, skips entries where `published_parsed=None`; converts to `datetime(..., tzinfo=timezone.utc)` | `rss_fetcher.py` | [HIGH] bozo handling |
| 7 | `rss_fetcher.py`: `strip_html()` via BeautifulSoup for Techmeme summaries | `rss_fetcher.py` | |
| 8 | `main.py` stub: `ThreadPoolExecutor` concurrent fetch, catch exceptions per-future in `as_completed()`, skip failed feeds with warning | `main.py` | [HIGH] thread exception |
| 9 | Use `Path(__file__).parent` for all output file paths | `main.py` | [MEDIUM] cwd dependency |

**Done when**: Console prints all articles; Techmeme `clean_summary` has no HTML tags; private IP URLs rejected; bad feeds skipped without crash.

---

## Sprint 2 — AI Processing

**Goal**: Connect GitHub Models, batch filter + summarize, prevent injection.

| # | Task | File | Security/Quality |
|---|---|---|---|
| 1 | `ai_processor.py`: `check_ai_relevance_batch(articles) -> list[bool]` — single gpt-4o-mini call, returns JSON array | `ai_processor.py` | [HIGH] N+1 API calls |
| 2 | `ai_processor.py`: system prompt wraps external content in `<article>` tags to isolate from instructions | `ai_processor.py` | [CRITICAL] Prompt Injection |
| 3 | `ai_processor.py`: `generate_summary(article) -> str` — per-article gpt-4o call, `time.sleep(0.5)` rate limiting | `ai_processor.py` | |
| 4 | `ai_processor.py`: catch OpenAI exceptions, log only `type(e).__name__` + `status_code`, never log raw exception (prevents token leakage) | `ai_processor.py` | [HIGH] token leakage |
| 5 | `main.py`: load `.env` via `python-dotenv`; fail fast with clear message if `GITHUB_TOKEN` missing; integrate cache skip logic | `main.py` | |

**Done when**: All articles filtered in one API call; prompt injection content has no effect; token never appears in logs; second run skips cached URLs.

---

## Sprint 3 — HTML Output & Polish

**Goal**: Generate safe final HTML, auto-open browser, handle edge cases.

| # | Task | File | Security/Quality |
|---|---|---|---|
| 1 | `html_generator.py`: Jinja2 `Environment(autoescape=True)`, URL fields additionally use `\|e` filter | `html_generator.py` | [CRITICAL] XSS |
| 2 | `html_generator.py`: two sections (Other Sources / Techmeme), card per article: title (hyperlink), AI summary, published datetime, source feed label | `html_generator.py` | |
| 3 | `main.py`: deduplicate articles by `article.url` before sorting | `main.py` | [MEDIUM] duplicate articles |
| 4 | `main.py`: sort key `lambda a: (a.is_techmeme, -a.published.timestamp())` — Techmeme last, newest first within each group | `main.py` | |
| 5 | `main.py`: write `output.html`, call `webbrowser.open(str(output_path))` | `main.py` | |
| 6 | `html_generator.py`: empty state — "No AI-related articles found." | `html_generator.py` | |

**Done when**: `python main.py` opens browser; XSS payloads in feed content are escaped; Techmeme section appears last; duplicates removed; all text in English.

---

## Security Summary

| Severity | Issue | Sprint |
|---|---|---|
| [CRITICAL] | Prompt injection via RSS content | Sprint 21 |
| [CRITICAL] | XSS in Jinja2 HTML output | Sprint 3 |
| [HIGH] | SSRF via unvalidated URLs in `feeds.txt` | Sprint 1 |
| [HIGH] | Thread exceptions silently swallowed | Sprint 1 |
| [HIGH] | `feedparser` bozo errors unhandled | Sprint 1 |
| [HIGH] | N+1 API calls for relevance check | Sprint 2 |
| [HIGH] | GITHUB_TOKEN leaked in exception logs | Sprint 2 |
| [MEDIUM] | datetime not timezone-aware | Sprint 1 |
| [MEDIUM] | Output path depends on cwd | Sprint 1 |
| [MEDIUM] | Duplicate articles across feeds | Sprint 3 |
| [LOW] | `cache.json` corruption on bad JSON | Sprint 1 |

---

## Pipeline (main.py)

```
.env → GITHUB_TOKEN
feeds.txt → validate URLs → ThreadPoolExecutor fetch_feed() →
  strip HTML (Techmeme) →
  load cache.json → skip cached URLs →
  check_ai_relevance_batch() [gpt-4o-mini, single call] →
  generate_summary() per AI-related article [gpt-4o, sleep 0.5] →
  save cache.json →
  filter AI-related → deduplicate by URL →
  sort (Techmeme last, newest first) →
  generate_html() [Jinja2, autoescape=True] →
  write output.html → webbrowser.open()
```

---

## Verification Checklist

- [ ] `python main.py` — progress printed, browser opens
- [ ] `output.html` — two sections, Techmeme cards after all others
- [ ] `cache.json` populated after first run
- [ ] Second run — no API calls for cached URLs
- [ ] Missing `GITHUB_TOKEN` — clear error, non-zero exit
- [ ] Feed with zero AI articles — "No AI-related articles found."
- [ ] Private IP in `feeds.txt` — rejected with warning
- [ ] Bad RSS URL — skipped with warning, other feeds continue
- [ ] XSS payload in feed title — escaped in HTML output
