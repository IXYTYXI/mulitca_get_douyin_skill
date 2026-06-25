---
name: douyin-scraper
description: "Use when the user asks to scrape Douyin data - keyword search, author profile, video details, comments, or trending topics. Covers the full pipeline: search, classify (video/image), download media, upload to Feishu bitable, scrape comments."
user-invocable: true
---

# Douyin Scraper Workflow

Use this skill when the user wants to scrape data from Douyin -- keyword search results, author profile posts, video details, comments, or trending topics -- and write the results to Feishu bitable.

## Prerequisites

### 1. Douyin Cookie (required for search and comments)

The user must provide a Douyin login Cookie. Without it, search results are limited and comments may be inaccessible.

How to get it:
1. Log into douyin.com in a browser
2. Open DevTools (F12) -> Network tab
3. Copy the Cookie header value from any request
4. Paste into `.env` file as `DOUYIN_COOKIE=...`

**Never ask the user to paste cookies in issue comments** -- cookies are login credentials.

### 2. Feishu App Credentials

The `.env` file needs:
- `FEISHU_APP_ID` -- from https://open.feishu.cn
- `FEISHU_APP_SECRET`
- `FEISHU_APP_TOKEN` -- the bitable's app token (from URL)

The Feishu app must have `bitable:app` permission enabled and published, and the bitable must add the app as a collaborator.

### 3. Playwright Browser

Install with `playwright install chromium` if not already installed.

## Full Pipeline (scrape_all.py)

The primary entry point for a complete scrape job is `scrape_all.py`. Configure via environment variables (or `.env` file):

```
VIDEO_TABLE_ID=tbl...    # Feishu table for video posts
IMAGE_TABLE_ID=tbl...    # Feishu table for image/note posts
COMMENT_TABLE_ID=tbl...  # Feishu table for comments
DOUYIN_KEYWORD=your_keyword
```

Then run:
```bash
cd douyin-scraper
python scrape_all.py
```

### What it does (4 steps)

1. **Search ALL posts** (video + image/note) for the keyword
2. **Download media** (cover images, videos, image post photos) and **upload to Feishu** as attachments
3. **Fetch first-level comments** for all posts via browser
4. **Write comments** to Feishu

## Two-Phase Search Strategy

Douyin's Web API behaves differently for video vs image/note content:

### Phase 1: Video posts via HTTP API (fast, no browser)

Uses `/search/item/` endpoint with Cookie-based auth. Returns only video-type posts.

### Phase 2: Image/note posts via browser API (requires Playwright)

Uses `/general/search/single/` with `aweme_image_web` channel. **Only works from a browser context** because it requires browser-generated security tokens.

The browser navigates to a video page first (avoids captcha), then calls the search API via `page.evaluate(fetch(...))`.

## CLI Commands (main.py)

For simpler one-off tasks:

```bash
python main.py search "keyword" -n 50       # Keyword search
python main.py user "https://..." -n 100     # Author profile
python main.py trending                       # Trending
python main.py video VIDEO_ID --comments     # Video details + comments
```

## Known Limitations

1. **Play count** -- Always 0 from Web API (Douyin anti-scraping).
2. **Reply comments** -- Only first-level comments are reliably scrapeable.
3. **Image posts** -- Some keywords return no image posts even through the browser API.
4. **Cookie expiration** -- Cookies expire after ~60 days.
5. **Rate limiting** -- Default 2-second delay between requests.
