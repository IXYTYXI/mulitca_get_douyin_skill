import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import click

# Windows 控制台默认 GBK，打印 emoji/中文诊断会崩，统一切到 replace 兜底。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass

from config.settings import XHS_COOKIE, XHS_BASE_URL
from core.browser import XhsBrowser, COOKIE_FILE, STEALTH_JS, USER_AGENT
from core.cookies import (
    parse_cookie_string,
    cookies_list_to_map,
    is_logged_in,
    login_diagnosis,
)
from scrapers.keyword import KeywordScraper
from core.cookies import NotLoggedInError
from storage.local import LocalStorage


@click.group()
def cli():
    """小红书数据爬取工具 —— 关键词搜索笔记（含 Cookie 登录检测）。"""
    pass


def _save_cookie_to_env(cookie_str: str):
    """把 XHS_COOKIE 写入/替换 .env（保留其他键）。"""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    lines = []
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    out, done = [], False
    for ln in lines:
        if ln.startswith("XHS_COOKIE="):
            out.append("XHS_COOKIE=" + cookie_str)
            done = True
        else:
            out.append(ln)
    if not done:
        out.append("XHS_COOKIE=" + cookie_str)
    with open(env_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out) + "\n")


@cli.command()
def check():
    """校验当前 Cookie 的登录态（读 cookies.json 或 .env 的 XHS_COOKIE）。"""
    if COOKIE_FILE.exists():
        try:
            with open(COOKIE_FILE, "r", encoding="utf-8") as f:
                jar = cookies_list_to_map(json.load(f))
            click.echo(f"来源: {COOKIE_FILE}")
        except Exception as e:
            click.echo(f"读取 cookies.json 失败: {e}")
            jar = parse_cookie_string(XHS_COOKIE)
            click.echo("回退来源: .env XHS_COOKIE")
    else:
        jar = parse_cookie_string(XHS_COOKIE)
        click.echo("来源: .env XHS_COOKIE")
    click.echo(login_diagnosis(jar))
    sys.exit(0 if is_logged_in(jar) else 1)


@cli.command()
@click.option("--timeout", default=300, help="等待登录的最长秒数（默认 300=5分钟）")
def login(timeout):
    """打开可见浏览器扫码登录小红书，自动检测并保存 Cookie。"""
    asyncio.run(_login(timeout))


async def _login(timeout=300):
    import time as _t
    from playwright.async_api import async_playwright
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass

    pw = await async_playwright().start()
    br = await pw.chromium.launch(
        headless=False,
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
    )
    ctx = await br.new_context(
        viewport={"width": 1440, "height": 900},
        user_agent=USER_AGENT,
        locale="zh-CN", timezone_id="Asia/Shanghai",
    )
    await ctx.add_init_script(STEALTH_JS)
    page = await ctx.new_page()
    try:
        await page.goto(XHS_BASE_URL, wait_until="domcontentloaded", timeout=60000)
    except Exception:
        pass

    click.echo("浏览器已打开。请扫码登录小红书，并完成任何滑块/验证码。")
    click.echo(f"检测到登录（web_session 写入）后会自动保存 Cookie；最多等待 {timeout} 秒。")

    def cookie_str(cookies):
        return "; ".join(f"{c['name']}={c['value']}" for c in cookies)

    start = _t.time()
    logged_in = False
    last_str = ""
    while _t.time() - start < timeout:
        await asyncio.sleep(5)
        cookies = await ctx.cookies()
        last_str = cookie_str(cookies)
        if last_str:
            with open(COOKIE_FILE, "w", encoding="utf-8") as f:
                json.dump(cookies, f, ensure_ascii=False, indent=2)
            _save_cookie_to_env(last_str)
        if is_logged_in(cookies_list_to_map(cookies)):
            logged_in = True
            await asyncio.sleep(3)
            cookies = await ctx.cookies()
            last_str = cookie_str(cookies)
            with open(COOKIE_FILE, "w", encoding="utf-8") as f:
                json.dump(cookies, f, ensure_ascii=False, indent=2)
            _save_cookie_to_env(last_str)
            break

    await br.close()
    await pw.stop()
    if logged_in:
        click.echo(f"\n✅ 检测到登录，Cookie 已保存（{len(last_str)} 字符）到 .env 和 cookies.json。")
    else:
        click.echo("\n⚠️ 超时未检测到登录（未发现 web_session）。请重试或确认已完成扫码。")


@cli.command()
@click.argument("keyword")
@click.option("--max-count", "-n", default=30, help="最大爬取笔记数量")
@click.option("--headless/--no-headless", default=True, help="无头/可见浏览器（过验证码时用 --no-headless）")
@click.option("--out", "out_name", default="", help="输出文件名（不含扩展名），默认按关键词命名")
def search(keyword, max_count, headless, out_name):
    """按关键词搜索小红书笔记并落盘（json + csv）。"""
    asyncio.run(_search(keyword, max_count, headless, out_name))


async def _search(keyword, max_count, headless, out_name):
    async with XhsBrowser() as browser:
        await browser.start(headless=headless)
        # 早失败：跑抓取前先给出登录诊断。
        if not await browser.verify_login():
            click.echo("\n未检测到有效登录态，抓取很可能返回空。请先 `python main.py login` "
                        "或在 .env 设置 XHS_COOKIE。")
        scraper = KeywordScraper(browser)
        try:
            notes = await scraper.search_notes(keyword, max_count)
        except NotLoggedInError as e:
            click.echo(f"\n{e}")
            sys.exit(1)

    records = [n.to_dict() for n in notes]
    if not records:
        click.echo("没有数据可输出。")
        return

    click.echo(f"\n共 {len(records)} 条笔记，示例前 5 条：")
    for r in records[:5]:
        click.echo(f"  · {r['title'][:30] or '(无标题)'} | 赞{r['liked_count']} | "
                   f"@{r['author_nickname']} | {r['note_url']}")

    name = out_name or f"search_notes_{keyword}"
    local = LocalStorage()
    local.save_json(records, f"{name}.json")
    local.save_csv(records, f"{name}.csv")


if __name__ == "__main__":
    cli()
