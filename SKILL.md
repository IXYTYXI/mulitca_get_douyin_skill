---
name: douyin-scraper
description: "Use when the user asks to scrape Douyin data - keyword search, author profile, video details, comments, or trending topics. Covers the full pipeline: search, classify (video/image), download media, upload to Feishu bitable, scrape comments."
user-invocable: true
---

# Douyin Scraper Workflow

Use this skill when the user wants to scrape data from Douyin -- keyword search results, author profile posts, video details, comments, or trending topics -- and write the results to Feishu bitable.

## Feishu Data Model — CANONICAL (do not deviate)

These are standing requirements from the project owner. **Always follow them when writing to Feishu; do not collapse or relabel.**

1. **Four separate tables** — never merge:
   | 表 | 内容 |
   |---|---|
   | **视频作品** | video posts only |
   | **图文作品** | image/note posts only |
   | **一级评论** | first-level comments |
   | **二级评论** | second-level (reply) comments |
2. **Upload the actual media files** (not just URLs) as Feishu **attachments**:
   - 视频作品: `作品封面` (cover) + `作品视频` (the real .mp4) — both attachments.
   - 图文作品: `作品封面` + `作品图片` (all images) — attachments.
3. **Link fields show the raw URL**, not a label. `作品链接` and `作者主页` (and `主页链接`) are URL fields whose displayed text **is the URL itself** — never "作品链接" / "查看作品" / a nickname. Build them with `storage.feishu.url_field(url)` → `{"link": url, "text": url}`.
4. **二级评论** carries `父评论ID` (the L1 comment it replies to) and `回复对象` (who it replies to).

The field schemas live in `storage/feishu.py` (`setup_video_table` / `setup_image_table` / `setup_comment_l1_table` / `setup_comment_l2_table`); attachment fields are type 17, URL fields type 15.

### How to produce it

```bash
# One shot: create the standard 4-table bitable in a folder AND run the full
# pipeline (posts split video/image with media uploaded + L1/L2 comments).
python main.py scrape-to-bitable "关键词" --folder <folder_token_or_url>

# Just create the 4-table structure (no scraping):
python main.py scrape-to-bitable "关键词" --folder <folder> --structure-only

# Skip comments (posts only):
python main.py scrape-to-bitable "关键词" --folder <folder> --no-comments
```

Reuse an existing bitable by setting `FEISHU_APP_TOKEN` + `VIDEO_TABLE_ID` / `IMAGE_TABLE_ID` / `COMMENT_L1_TABLE_ID` / `COMMENT_L2_TABLE_ID` in `.env`, then run `python scrape_all.py`.

## First-Run Setup

The scraper code ships as supporting files with this skill. On first use, the agent must set up the environment:

### Step 1: Check out the repo

```bash
multica repo checkout https://github.com/IXYTYXI/mulitca_get_douyin_skill.git
```

This clones the code into the working directory. If the directory already has the code (check for `scrape_all.py`), skip this step.

### Step 2: Install Python dependencies

```bash
cd mulitca_get_douyin_skill   # or wherever the checkout landed
pip install -r requirements.txt
playwright install chromium
```

### Step 3: Configure credentials

Copy `.env.example` to `.env` and fill in:

```bash
cp .env.example .env
```

The user needs to provide (ask them via issue comment if missing -- but **never ask for cookies in comments**, tell them to configure it on their runtime):

| Variable | Where to get it | Required |
|---|---|---|
| `DOUYIN_COOKIE` | Login to douyin.com, copy Cookie from DevTools > Network | Yes |
| `FEISHU_APP_ID` | https://open.feishu.cn, create an app | Yes |
| `FEISHU_APP_SECRET` | Same app page | Yes |
| `FEISHU_APP_TOKEN` | From the Feishu bitable URL | Yes |
| `VIDEO_TABLE_ID` | Create a table in the bitable, copy its ID | Yes |
| `IMAGE_TABLE_ID` | Create a second table | Yes |
| `COMMENT_TABLE_ID` | Create a third table | Yes |
| `DOUYIN_KEYWORD` | The search keyword | Yes |

**Security:** Never log, print, or post credentials in issue comments. If .env is missing, tell the user to configure it on their runtime directly.

### Step 4: Verify setup

```bash
python main.py search "test" -n 1
```

If this returns results, the setup is correct.

## Running the Full Pipeline

The primary entry point is `scrape_all.py`:

```bash
python scrape_all.py
```

### What it does (4 steps)

1. **Search ALL posts** (video + image/note) for the keyword
2. **Download media** (cover images, videos, image post photos) and **upload to Feishu** as attachments
3. **Fetch first-level comments** for all posts via browser
4. **Write comments** to Feishu

### Changing the keyword

Set `DOUYIN_KEYWORD` in `.env` to a new value, then re-run `python scrape_all.py`. If you want separate tables for different keywords, create new tables in Feishu and update the table ID variables.

## Two-Phase Search Strategy

Douyin's Web API behaves differently for video vs image/note content:

### Phase 1: Video posts via HTTP API (fast, no browser)

Uses `/search/item/` endpoint with Cookie-based auth. Returns only video-type posts (aweme_type=0).

### Phase 2: Image/note posts via browser API (requires Playwright)

Uses `/general/search/single/` with `aweme_image_web` channel. **Only works from a browser context** because it requires browser-generated security tokens.

The browser navigates to a specific video page first (avoids captcha), then calls the search API via `page.evaluate(fetch(...))`. First 1-2 attempts often time out; the code retries up to 3 times automatically.

### Post type detection

Image posts: `aweme_type` in (68, 150), or `media_type == 2`, or `images` array is non-empty.
Video posts: everything else. Image posts use `/note/{id}` URLs; video posts use `/video/{id}`.

## Date / Time Range Filtering

Search results can be limited by publish time through two complementary mechanisms (shared logic lives in `core/datefilter.py`, used by both entry points and both search phases):

### 1. Predefined range (`publish_time`) — server-side

Douyin's search API understands a coarse `publish_time` filter, passed via `filter_selected`:

| Value | Meaning |
|-------|---------|
| `0`   | 不限 (no limit, default) |
| `1`   | 一天内 (within 1 day) |
| `7`   | 一周内 (within 1 week) |
| `182` | 半年内 (within half a year) |

### 2. Custom range (`start_date` / `end_date`) — client-side

The API has no native arbitrary-date support, so any custom window is enforced client-side using each result's `create_time`. Bounds are **inclusive** and the end date covers the whole day (up to `23:59:59`). Posts outside the window — or with a missing timestamp — are dropped.

Pagination advances by the **raw discovered count**, so a page whose results are entirely trimmed by the date filter still pages on toward older posts instead of stopping early. Crawling is still capped by `MAX_PAGES`.

### Usage

CLI (`main.py search`, video search only):

```bash
# Predefined: posts from the last week
python main.py search "keyword" --publish-time 7

# Custom window: 2025-01-01 .. 2025-06-01 (both inclusive)
python main.py search "keyword" --start-date 2025-01-01 --end-date 2025-06-01

# Open-ended: everything since 2025-01-01
python main.py search "keyword" --start-date 2025-01-01
```

Full pipeline (`scrape_all.py`) — via environment variables / `.env`:

```bash
DOUYIN_PUBLISH_TIME=7                 # predefined range (0/1/7/182)
DOUYIN_START_DATE=2025-01-01          # custom lower bound (inclusive)
DOUYIN_END_DATE=2025-06-01            # custom upper bound (inclusive)
```

Invalid input is rejected up front: a malformed date, a `publish_time` outside `{0,1,7,182}`, or a `start-date` later than `end-date` all raise a clear error before any network call.

## CLI Commands (main.py)

For simpler one-off tasks (no full pipeline needed):

```bash
python main.py search "keyword" -n 50       # Keyword search (video only)
python main.py search "keyword" --publish-time 7              # ...within the last week
python main.py search "keyword" --start-date 2025-01-01 --end-date 2025-06-01  # ...custom date range
python main.py user "https://..." -n 100     # Author profile (all post types)
python main.py trending                       # Trending videos
python main.py video VIDEO_ID --comments     # Single video details + comments
```

### Create a new Bitable and write into it (reusable)

`scrape-to-bitable` creates a **new** Feishu Bitable (optionally inside a Drive folder), scrapes a keyword, and writes the results — so you get a reusable table in one shot:

```bash
# Create the table inside a Drive folder (pass the folder token or its URL)
python main.py scrape-to-bitable "咖啡" --folder ZvZ0fN9YdlYt26dGCMDcDjo3nMc -n 50 --start-date 2025-01-01 --end-date 2025-06-01
```

It prints the new `app_token` / `table_id` / URL. To **reuse** that table later, set `FEISHU_APP_TOKEN=<app_token>` in `.env`.

> **Folder permission:** creating a Bitable inside a folder requires the self-built app to be a **collaborator with edit rights** on that folder, and the app must have `drive:drive` + `bitable:app` permissions published. Otherwise Feishu returns `DriveNodePermNotAllow` — share the folder with the app, then retry. Omit `--folder` to create the file in the app's own space instead.

## Rate Limiting & Delay Strategy

Douyin throttles requests that are too fast **or too regular**. When it triggers, the search endpoints usually still return HTTP 200 but with `status_code == 0` and an **empty `data` array** — which a naive scraper misreads as "no more results" and stops early. The scraper guards against this in `core/throttle.py`:

- **Jittered delays** — every request waits `REQUEST_DELAY` ± `REQUEST_JITTER` (randomized), so the cadence isn't a fixed robotic beat.
- **Exponential backoff** — transport errors retry with growing waits (`BACKOFF_FACTOR`, capped at `BACKOFF_MAX`).
- **Empty/blocked retry** — an unexpectedly empty page is treated as a throttle signal and retried up to `EMPTY_RETRY` times with backoff before giving up. Applied to the HTTP search (Phase 1), the browser image search (Phase 2), and keyword search.

Tuning knobs (env / `.env`, defaults shown):

| Var | Default | Effect |
|-----|---------|--------|
| `REQUEST_DELAY` | `2` | Base seconds between requests |
| `REQUEST_JITTER` | `0.4` | Random ± fraction of the base delay |
| `EMPTY_RETRY` | `2` | Retries on an empty/blocked page |
| `REQUEST_MAX_RETRIES` | `3` | Retries on transport errors |
| `BACKOFF_FACTOR` | `2.0` | Exponential growth per retry |
| `BACKOFF_MAX` | `30` | Cap on a single backoff (s) |

If you still see frequent empty results, raise `REQUEST_DELAY` (e.g. `4`–`6`) and/or `EMPTY_RETRY`. Persistent zero results across all keywords usually means the cookie expired, not rate limiting — re-login per Troubleshooting.

### Headless vs headed browser

The image-search phase (Phase 2) and comment scraping use Playwright. In some runtimes the **headless** browser crashes (`TargetClosedError`) and image posts come back empty. Run with a **visible/local browser** instead — it is more stable and trips Douyin's anti-bot less:

```bash
python main.py scrape-to-bitable "关键词" --folder <folder> --headed
# or for scrape_all.py: set DOUYIN_HEADLESS=0
```

Note: `--headed` improves **image search** stability but does **not** unblock **second-level (reply) comments** — the reply endpoint is guarded by `bd-ticket-guard` and returns empty regardless of headless/headed. First-level comments and video search work in both modes.

## Known Limitations

1. **Play count** -- Always 0 from Web API. Douyin blocks this for all third-party tools.
2. **Reply comments** -- Only first-level comments are reliably scrapeable. The reply API has stricter security.
3. **Image posts in search** -- Some keywords return no image posts even through the browser API. This is Douyin backend behavior (App and Web results differ).
4. **Cookie expiration** -- Cookies expire after ~60 days. If auth errors occur, re-login and update the cookie.
5. **Rate limiting** -- Requests are paced with a jittered delay + exponential backoff and empty-page retries (see "Rate Limiting & Delay Strategy"). Tune via `REQUEST_DELAY` / `REQUEST_JITTER` / `EMPTY_RETRY`. Headless browser may still trigger verification.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError` | Dependencies not installed | `pip install -r requirements.txt` |
| `playwright._impl._errors.Error` | Chromium not installed | `playwright install chromium` |
| Empty search results | Cookie expired or missing | Update `DOUYIN_COOKIE` in `.env` |
| All posts are videos, no images | Normal for some keywords | Try a different keyword or use author profile scraping |
| Browser timeout on first attempt | Douyin rate limiting | Automatic retry handles this; if persistent, wait a few minutes |
| Feishu write fails | App not authorized or table ID wrong | Check Feishu app permissions and table IDs |
