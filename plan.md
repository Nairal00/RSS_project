RSS AI News Digest — Project Plan

## Overview

A Python CLI script that fetches multiple RSS feeds within a given time range, uses Deepseek model to summarize and score them, sorts with the highest score, generates a styled local HTML digest, and auto-opens it in the browser. Complied with flake8, pylint and pytest coverage is over 95%. 

## Dependencies (`requirements.txt`)

| Package | Purpose |
|---|---|
| `feedparser` | Parse RSS/Atom feeds |
| `requests` | Fetch article content via Jina AI reader |
| `openai` | DeepSeek API calls (OpenAI-compatible SDK) |
| `pytest` | Test framework |
| `pytest-cov` | Test coverage |
| `flake8~=7.1.1` | Linting |
| `pylint~=3.3.4` | Linting |

> `time`, `re` are standard library — no install needed.

## Sprint 1 — Foundation & Data Pipeline

**Goal**: Fetch RSS data within a given time range, proper error handling, parse into structured objects, establish security boundaries.
1. Read the system time and convert it into a UTC time
2. The time range is 24 hours before the given the system time. Should not be hard-coded,use a constant.
3. Read the sources from the feeds.txt using a context manager (`with open(...)`); if the file does not exist or the path is wrong, print an error message and exit with `sys.exit(1)`
4. If error is found in requesting any feed, print the error code and message to console, then skip that feed and continue with the rest. Store the error info for later display in Sprint 4/5.
5. Parse the feed into title and link, description if any.
   - If an article's link field is empty or the link is broken, log an error with the feed source name and the article's published time; skip the article; collect the error for final output display.
   - If an article's published time field is missing or malformed, log an error with the article title and link; skip the article; collect the error for final output display.
6. All functions must have type hints.

**Done when**: private IP URLs rejected; bad feed requests show error code and message. If no update found in any of the feeds, display no update from the particular source. Articles found during parsing are **collected but NOT printed immediately**; they are printed once only in the final output. Tests written for: normal feed, private IP rejection, empty feed, missing `feeds.txt`, empty article link, malformed publised time and empty or broken link field.

## Sprint 2 — Extract the header and message from the given link
**Goal**: Extract the header and message from the given link.
1. Apply the same private IP / URL validation as Sprint 1 to each article link before passing it to Jina (SSRF prevention)
2. Fetch clean text via `https://r.jina.ai/{link}`; if Jina returns an empty response body, do not save a file — log error "Jina无法读取网页信息" and skip the article.
3. Sanitize the filename before saving: lowercase the title, replace spaces with `_`, remove any character that is not alphanumeric or `_`, truncate to 50 characters. If the sanitized result is empty, fall back to the first 8 characters of the article URL's hex hash. Final filename: `{source}_{sanitized_title}.md` saved in the current working directory using a context manager (`with open(...)`). If a file with the same name already exists, overwrite it.
4. All functions must have type hints.

**Done when**: Strip formatting, images, image links, and hyperlinks. Each article saved to a markdown file. Private IP links rejected before calling Jina. Proper error handling. Tests written for: successful fetch, Jina request error, private IP rejection, empty-title filename fallback, empty Jina response body.

## Sprint 3 — Call Deepseek API to summarize the extracted article and rate based on a given criteria
**Goal**: Use Deepseek API to summarize each article and assign a score.

**API call specifics**:
- **SDK**: `openai` Python package (OpenAI-compatible interface) — DeepSeek has no official SDK
- **Base URL**: `https://api.deepseek.com` — fixed constant, define as `DEEPSEEK_BASE_URL`
- **Model**: `deepseek-v4-flash` — define as `DEEPSEEK_MODEL` constant
- Instantiate once: `OpenAI(api_key=..., base_url=DEEPSEEK_BASE_URL)`

1. Remove all functions related to saving article content locally; keep article extraction and markdown-cleaning in memory, then send the cleaned content directly to the model.
2. Read Deepseek API key from environment variable (e.g. `DEEPSEEK_API_KEY`) — never hardcode it.
   - Only missing API key should immediately print an error and exit with `sys.exit(1)`.
3. Define scoring criteria as a constant `SCORE_PROMPT` (the prompt fed to the model).
4. For each API call, send `SCORE_PROMPT` as `role: system` and the article content as `role: user` — do NOT concatenate them into a single string (prompt injection prevention).
5. Set `response_format={'type': 'json_object'}` and include expected JSON format example in `SCORE_PROMPT` (DeepSeek JSON Output mode).
6. Parse the API response with `json.loads()` to extract `summary` and `score` (score must be `0` or `1`).
   - Total attempts per article: at most 2 (initial 1 + retry 1).
   - If `score` is outside `0` or `1`, print an error, retry once, and if still invalid then skip the article.
   - If `summary` or `score` is `null`, print an error, retry once, and if still invalid then skip the article.
   - If response JSON is malformed, print an error, retry once, and if still malformed then skip the article.
7. For all skipped/problematic articles, store and display their Jina-cleaned original text and the specific errorin the final error section.
8. Output ordering — two sections printed in sequence:
   - **Section 1 — updated feeds**: all successfully scored articles, sorted globally by `score` descending; use published time (closest to current time first) as tiebreaker for equal scores. Articles from different sources may interleave.
   - **Section 2 — no-update / error feeds**: all feed sources that either returned no new articles within the time window *or* encountered any error (network, parse, Jina, API, etc.), listed after all scored articles. Format stays `[{source}] No update in the last {TIME_RANGE_HOURS} hours.` for silent feeds; existing error format for errored feeds.
9. Insert a `SAME_SOURCE_SLEEP_SECS` delay between consecutive Jina requests for the same source to avoid triggering target-site rate limiting. No delay is added between requests from different sources.
10. All functions must have type hints.

**Done when**: Each valid article has a summary and a rating; The score articles do not need to print out the score. Scored articles printed first (score descending, time tiebreaker), followed by no-update and errored feed sources at the end; each article printed exactly once (no duplicate from fetch-time print); API key is loaded from environment variable; missing API key exits immediately; output/JSON/score/null errors are retried once and then skipped if still invalid; problematic articles and errors are listed with their Jina-cleaned original text at the end. Tests written for: valid API response, malformed JSON response (retry then skip), missing API key, score sorting, score out of range (retry then skip), null summary/score (retry then skip).

## Sprint 4 — HTML Generation & Browser Launch
**Goal**: Generate a styled local HTML digest in a given newsletter format and auto-open it in the browser.

1. Implement `generate_html(articles, errors, silent_sources, title, now) -> str` in `html_generator.py`:
   - Head: `DOCTYPE`, charset/viewport meta, MS Office XML compat comments, and an inline `<style>` block (georgia serif, 600px max-width, `#dcdcdc` dividers, `#286ed0` accent blue, `@media (max-width:480px)` responsive rules)
   - Body: centered 600px-max table wrapper
   - Header block: newsletter title + date (e.g. `May 26, 2026`) with bottom border
   - Intro blurb: italic georgia paragraph — fixed text `"Top stories from the past 24 hours, sorted by AI."`
   - Article loop — for each article:
     - `border-top: 1px solid #dcdcdc` row separator
     - `<h3>` title linked to `article.link` (700 20px/25px georgia, color `#000`)
     - `<p>` summary (fall back to `description` if `summary` is `None`) — 17px/22.5px georgia, color `#333`
     - Source byline — 600 13px/18px arial, color `#000`
   - Footer: generation timestamp; error count if any (12px arial, color `#666`)
   - Apply `html.escape()` to **all** external strings written into HTML: titles, summaries, descriptions, sources, error messages, and links used in `href` attributes (XSS prevention)
2. Add `NEWSLETTER_TITLE = 'Daily Digest'` and `HTML_OUTPUT_PATH = 'digest.html'` constants to `config.py`
3. In `main.py`, after `run()`, call `generate_html(...)` and write output to `HTML_OUTPUT_PATH` using a context manager (`with open(...)`)
4. Auto-open `digest.html` in the default browser using `webbrowser.open()`; pass the path as a local file URI via `pathlib.Path.as_uri()` to prevent arbitrary URL navigation

**Done when**: `digest.html` is written on every run; opening in a browser shows all scored articles with title/summary/source/link, newsletter header with today's date, and a footer with error count; `html.escape()` applied to all user-derived strings; existing tests still pass; tests written for: correct HTML structure, `html.escape()` applied, empty article list renders without error, articles with `summary=None` fall back to `description`.

## Sprint 5 — Consolidate Validation into `validators.py`

**Goal**: Eliminate duplicated validation logic across modules by centralising all URL/link checks in `validators.py`.

### Before / After

| 文件 | 函数 | 重构前 | 重构后 |
|---|---|---|---|
| `validators.py` | `is_http_url()` | ❌ 不存在，3处内联重复（`load_feeds`、`_parse_entries`、`_safe_href`） | 🆕 新增，统一替换3处 |
| `validators.py` | `has_control_chars()` | ❌ 不存在，`content_extractor` 内联 `any(c in link ...)` | 🆕 新增，替换内联检查 |
| `validators.py` | `is_private_url()` | ✅ 已存在 | ✅ 保留 |
| `feed_fetcher.py` | `load_feeds()` | 内联 `urlparse(url).scheme not in ('http', 'https')`，无控制字符检查 | 改调 `not is_http_url(url)`，补加 `has_control_chars(url)` 检查 |
| `feed_fetcher.py` | `_parse_entries()` | 内联 `not link.startswith(('http://', 'https://'))` | 改调 `not is_http_url(link)` |
| `content_extractor.py` | `fetch_article_content()` | 内联 `any(c in article.link for c in ('\r', '\n', '\x00'))` | 改调 `has_control_chars(article.link)` |
| `html_generator.py` | `_safe_href()` | 内联 `urlparse(link).scheme in ('http', 'https')` | 改调 `is_http_url(link)` |

### Security requirements

1. [HIGH] `is_http_url()` **必须用 `urlparse(url).scheme in ('http', 'https')`**，禁止用 `startswith()`。原因：现有3处内联实现不一致，`_parse_entries` 用 `startswith()` 对大写 scheme（`HTTP://`、`HTTPS://`）失效；统一后必须保证大小写不敏感。
2. [MEDIUM] `load_feeds()` 在 scheme 检查之后**还需调用 `has_control_chars(url)`**（Sprint 5 的 Before/After 表未覆盖此点）。原因：若 `feeds.txt` 含 `\r\n` 的 URL，能通过 scheme 检查，随后在 `fetch_feed()` → `requests.get(url)` 触发 HTTP 头注入。

### Tests
- 在 `tests/test_validators.py` 新增 `is_http_url()` 和 `has_control_chars()` 的单元测试
  - `is_http_url()` 需覆盖：`http://`、`https://`、大写 `HTTP://`、`ftp://`、空字符串
  - `has_control_chars()` 需覆盖：含 `\r`、含 `\n`、含 `\x00`、干净 URL
- `test_feed_fetcher.py` 新增：feed URL 含控制字符时被 `load_feeds()` 拒绝
- 验证 `test_feed_fetcher.py`、`test_content_extractor.py`、`test_html_generator.py` 现有测试继续通过

**Done when**: 没有内联 scheme 或控制字符检查留在 `validators.py` 以外；`is_http_url()` 用 `urlparse` 实现；`load_feeds()` 同时调用 `is_http_url` 和 `has_control_chars`；新测试覆盖上述场景；flake8 和 pylint 无新警告。

## Sprint 6 — SRP Refactor for `run()` and `main()`

**Goal**: Enforce Single Responsibility Principle — `run()` 承担了5个职责，`main()` 混入了输出副作用，拆分到正确模块。

### Issues (code checklist)

1. [MEDIUM] `run()` 混合了：env bootstrap、时间窗口、feed聚合、文章enrichment、排序
2. [MEDIUM] `main()` 混合了：CLI编排 + 文件写入 + 开浏览器
3. [LOW] 跨模块编排散落在入口文件，单元测试需要大量 mock

### Before / After

| 文件 | 函数 | 重构前 | 重构后 | 原因 |
|---|---|---|---|---|
| `main.py` | `get_utc_now()` | ✅ 存在 | ✅ 保留 | |
| `main.py` | `run()` | ✅ 存在，承担5个职责 | ❌ 删除 | 职责过多，违反SRP |
| `main.py` | `main()` | ✅ 存在，含文件写入+开浏览器 | ✅ 精简为纯编排 | 输出副作用移出 |
| `pipeline.py` | `collect_scored_articles()` | ❌ 不存在，逻辑在 `run()` 里 | 🆕 新建文件+函数 | 业务流编排不属于任何单一domain模块 |
| `summarizer.py` | `build_deepseek_client_from_env()` | ❌ 不存在，逻辑在 `run()` 里 | 🆕 新增 | bootstrap属于model层，不是入口层 |
| `summarizer.py` | `call_deepseek()` / `_redact()` | ✅ 存在 | ✅ 保留 | |
| `feed_fetcher.py` | `compute_since_window()` | ❌ 不存在，逻辑在 `run()` 里 | 🆕 新增 | 时间窗口是feed抓取的配套策略 |
| `feed_fetcher.py` | `load_feeds()` / `fetch_feed()` / `_parse_*()` | ✅ 存在 | ✅ 保留 | |
| `content_extractor.py` | `fetch_article_content()` / `strip_markdown()` | ✅ 存在 | ✅ 保留 | |
| `html_generator.py` | `write_digest()` | ❌ 不存在，逻辑在 `main()` 里 | 🆕 新增 | 输出副作用归HTML模块 |
| `html_generator.py` | `open_digest()` | ❌ 不存在，逻辑在 `main()` 里 | 🆕 新增 | 输出副作用归HTML模块 |
| `html_generator.py` | `generate_html()` / `_render_*()` / `_safe_href()` | ✅ 存在 | ✅ 保留 | |
| `models.py` | `Article` / `FeedError` | ✅ 存在 | ✅ 不变 | |

### `pipeline.py` 的职责边界

`pipeline.collect_scored_articles()` 负责编排，不负责实现：
- **调用** `load_feeds` / `fetch_feed`（实现在 `feed_fetcher.py`）
- **遍历**文章，控制同源 sleep 节流策略
- **调用** `fetch_article_content`（实现在 `content_extractor.py`）
- **调用** `call_deepseek`（实现在 `summarizer.py`）
- **汇总** errors 和 silent_sources（跨模块，只有编排层能做）
- **排序** articles（全局决策，依赖完整集合）

### 重构后 `main()` 序列

```
now    = get_utc_now()
client = build_deepseek_client_from_env()        # summarizer.py
since  = compute_since_window(now)               # feed_fetcher.py
articles, errors, silent = collect_scored_articles(...)  # pipeline.py
html   = generate_html(...)                      # html_generator.py
path   = write_digest(html, ...)                 # html_generator.py
open_digest(path)                                # html_generator.py
```

### Security guardrails

1. [HIGH] API key redaction 保留，不得出现在日志/错误信息
2. [MEDIUM] `build_deepseek_client_from_env()` 中 `OpenAI()` 构造器**必须包在 try/except 里**，异常消息通过 `_redact(str(exc), api_key)` 处理后再 print/exit。原因：SDK 某些版本的异常 repr 含配置信息，不脱敏会泄露 key。
3. [MEDIUM] `write_digest()` 内部必须将 `output_path` 解析为绝对路径（`Path(output_path).resolve()`），确保不会因未来 CLI `--output` 参数引入路径穿越（`../../etc/...`）风险。
4. [MEDIUM] 保留所有 SSRF 检查调用点（Sprint 5 成果不得回退）
5. [MEDIUM] 保留 `SAME_SOURCE_SLEEP_SECS` 节流行为
6. [LOW] `pipeline.py` 内任何涉及 `client` 的异常处理，**禁止直接打印 `client` 对象**；必须使用 `_redact(str(exc), client.api_key)` 模式。

### Tests

- 新增：`summarizer.build_deepseek_client_from_env`（缺key exit路径）
- 新增：`feed_fetcher.compute_since_window`（边界时间）
- 新增：`pipeline.collect_scored_articles`（mock网络+模型）
- 新增：`html_generator.write_digest` / `open_digest`（mock文件+浏览器）
- 保留：所有现有测试继续绿色

**Done when**: `main.py` 只剩7行编排调用；`run()` 删除；新增7个函数分布在各自归属模块；`pytest` / `flake8` / `pylint` 全部通过。

