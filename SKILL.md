---
name: douyin-scraper
description: "Use when the user asks to scrape Douyin data - keyword search, author profile, video details, comments, or trending topics. Covers the full pipeline: search, classify (video/image), download media, upload to Feishu bitable, scrape comments."
user-invocable: true
---

# Douyin Scraper Workflow

Use this skill when the user wants to scrape data from Douyin -- keyword search results, author profile posts, video details, comments, or trending topics -- and write the results to Feishu bitable.

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

## CLI Commands (main.py)

For simpler one-off tasks (no full pipeline needed):

```bash
python main.py search "keyword" -n 50       # Keyword search (video only)
python main.py user "https://..." -n 100     # Author profile (all post types)
python main.py trending                       # Trending videos
python main.py video VIDEO_ID --comments     # Single video details + comments
```

## Known Limitations

1. **Play count** -- Always 0 from Web API. Douyin blocks this for all third-party tools.
2. **Reply comments** -- Only first-level comments are reliably scrapeable. The reply API has stricter security.
3. **Image posts in search** -- Some keywords return no image posts even through the browser API. This is Douyin backend behavior (App and Web results differ).
4. **Cookie expiration** -- Cookies expire after ~60 days. If auth errors occur, re-login and update the cookie.
5. **Rate limiting** -- Default 2-second delay between API requests. Headless browser may trigger verification.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError` | Dependencies not installed | `pip install -r requirements.txt` |
| `playwright._impl._errors.Error` | Chromium not installed | `playwright install chromium` |
| Empty search results | Cookie expired or missing | Update `DOUYIN_COOKIE` in `.env` |
| All posts are videos, no images | Normal for some keywords | Try a different keyword or use author profile scraping |
| Browser timeout on first attempt | Douyin rate limiting | Automatic retry handles this; if persistent, wait a few minutes |
| Feishu write fails | App not authorized or table ID wrong | Check Feishu app permissions and table IDs |
