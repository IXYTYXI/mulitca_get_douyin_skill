# Douyin Scraper - Multica Skill

A Multica skill for scraping Douyin data (keyword search, author profiles, video details, comments, trending) and writing results to Feishu bitable.

## Features

- Keyword search: video + image/note posts (two-phase strategy)
- Author homepage mode: follower count (粉丝量) + selected posts (skips pinned) + comments → 5-table bitable
- Author profile scraping
- Video detail & comment extraction
- Feishu bitable integration with media attachments
- Browser-based scraping for image/note posts via Playwright

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt
playwright install chromium

# 2. Configure
cp .env.example .env
# Edit .env with your credentials

# 3. Run full pipeline
python scrape_all.py

# Or use CLI for specific tasks
python main.py search "keyword" -n 50

# Author homepage: profile (粉丝量) + posts + comments into a new 5-table bitable
python main.py scrape-author "https://www.douyin.com/user/MS4wLjABAAAA..." --folder <folder>
```

## Import as Multica Skill

```bash
multica skill import --url https://github.com/IXYTYXI/mulitca_get_douyin_skill --output json
```

See [SKILL.md](SKILL.md) for full documentation.

## Configuration

Copy `.env.example` to `.env` and fill in:

| Variable | Description |
|---|---|
| `FEISHU_APP_ID` | Feishu app ID |
| `FEISHU_APP_SECRET` | Feishu app secret |
| `FEISHU_APP_TOKEN` | Bitable app token |
| `VIDEO_TABLE_ID` | Feishu table for video posts |
| `IMAGE_TABLE_ID` | Feishu table for image/note posts |
| `COMMENT_TABLE_ID` | Feishu table for comments |
| `DOUYIN_KEYWORD` | Search keyword |
| `DOUYIN_COOKIE` | Douyin login cookie |

## License

MIT
