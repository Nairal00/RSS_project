RSS AI News Digest — Project Plan

## Overview

A Python CLI script that fetches multiple RSS feeds within a given time range, uses Deepseek model to summarize and score them, sorts with the highest score, generates a styled local HTML digest, and auto-opens it in the browser. Complied with flake8, pylint and pytest coverage is over 95%. 

## Dependencies (`requirements.txt`)

| Package | Purpose |
|---|---|
| `feedparser` | Parse RSS/Atom feeds |
| `requests` | Fetch article content via Jina AI reader |
| `pytest` | Test framework |
| `pytest-cov` | Test coverage |
| `flake8~=7.1.1` | Linting |
| `pylint~=3.3.4` | Linting |

> `time`, `re` are standard library — no install needed.

## Sprint 1 — Foundation & Data Pipeline

**Goal**: Fetch RSS data within a given time range, proper error handling, parse into structured objects, establish security boundaries.
1. Read the system time and convert it into a UTC time
2. The time range is 24 hours before the given the system time. Should not be hard-coded,use a constant
3. Read the sources from the feeds.txt using a context manager (`with open(...)`); if the file does not exist or the path is wrong, print an error message and exit with `sys.exit(1)`
4. If error is found in requesting any feed, print the error code and message to console, then skip that feed and continue with the rest. Store the error info for later display in Sprint 4/5.
5. Parse the feed into title and link, description if any.
   - If an article's link field is empty or the link is broken, log an error with the feed source name and the article's published time; skip the article; collect the error for final output display.
   - If an article's published time field is missing or malformed, log an error with the article title and link; skip the article; collect the error for final output display.
6. All functions must have type hints.

**Done when**: Console prints all titles(if any) and their link; private IP URLs rejected; bad feed requests show error code and message. If no update found in any of the feeds, display no update from the particular source. Tests written for: normal feed, private IP rejection, empty feed, missing `feeds.txt`, empty article link, malformed publised time and empty or broken link field.

## Sprint 2 — Extract the header and message from the given link
**Goal**: Extract the header and message from the given link.
1. Apply the same private IP / URL validation as Sprint 1 to each article link before passing it to Jina (SSRF prevention)
2. Fetch clean text via `https://r.jina.ai/{link}`; if Jina returns an empty response body, do not save a file — log error "Jina无法读取网页信息" and skip the article.
3. Sanitize the filename before saving: lowercase the title, replace spaces with `_`, remove any character that is not alphanumeric or `_`, truncate to 50 characters. If the sanitized result is empty, fall back to the first 8 characters of the article URL's hex hash. Final filename: `{source}_{sanitized_title}.md` saved in the current working directory using a context manager (`with open(...)`). If a file with the same name already exists, overwrite it.
4. All functions must have type hints.

**Done when**: Strip formatting, images, image links, and hyperlinks. Each article saved to a markdown file. Private IP links rejected before calling Jina. Proper error handling. Tests written for: successful fetch, Jina request error, private IP rejection, empty-title filename fallback, empty Jina response body.

## Sprint 3 — Call Deepseek API to summarize the article and rate a score based on a given criteria
**Goal**: Use Deepseek API to summarize each article and assign a score.
1. Read Deepseek API key from environment variable (e.g. `DEEPSEEK_API_KEY`) — never hardcode it
2. Define scoring criteria as a constant `SCORE_PROMPT` (the prompt fed to the model)
3. For each API call, send `SCORE_PROMPT` as `role: system` and the article content as `role: user` — do NOT concatenate them into a single string (prompt injection prevention)
4. Set `response_format={'type': 'json_object'}` and include expected JSON format example in `SCORE_PROMPT` (DeepSeek JSON Output mode — guarantees valid JSON, no schema enforcement needed)
5. Parse the API response with `json.loads()` to extract `summary` and `score` (scale: 0–100).
   - If `score` is outside 0–100, retry the API call three times. If the second response is still out of range, log an error and skip the article.
   - If `summary` or `score` is `null`, retry the API call three times. If the problem insists, print an error message and exit with `sys.exit(1)`.
6. Sort all articles by score descending; use published time (closest to system time first) as the tiebreaker when scores are equal.
7. All functions must have type hints.

**Done when**: Each article has a summary and a numeric score; articles are sorted by score descending with published-time tiebreaker; API key loaded from environment variable; API errors are handled gracefully. Tests written for: valid API response, malformed JSON response, missing API key, score sorting, score out of range (retry), null summary/score.

## Future Sprints (Sprint 4+)
- **Sprint 4 — HTML generation**: Apply `html.escape()` to all external strings (titles, summaries) before writing into HTML to prevent XSS
- **Sprint 5 — Auto-open browser**

