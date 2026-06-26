import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import click

from core.client import DouyinClient
from core.browser import DouyinBrowser
from scrapers.keyword import KeywordScraper
from scrapers.user import UserScraper
from scrapers.video import VideoScraper
from scrapers.trending import TrendingScraper
from core.datefilter import DateFilter
from storage.feishu import (
    FeishuBitable,
    video_to_feishu_record,
    user_to_feishu_record,
    comment_to_feishu_record,
    trending_to_feishu_record,
)
from storage.local import LocalStorage
from config.settings import DOUYIN_COOKIE, FEISHU_APP_ID


@click.group()
def cli():
    """抖音数据爬取工具 — 支持关键词搜索、作者主页、评论、热搜"""
    pass


@cli.command()
def login():
    """打开浏览器登录抖音，保存 Cookie 供后续爬取使用"""
    asyncio.run(_login())


async def _login():
    browser = DouyinBrowser()
    await browser.start(headless=False)
    click.echo("浏览器已打开，请在浏览器中：")
    click.echo("  1. 登录你的抖音账号")
    click.echo("  2. 如果出现验证码，请手动完成验证")
    click.echo("  3. 登录成功后，尝试搜索一个关键词确认正常")
    click.echo("  4. 完成后回到终端按回车键保存 Cookie\n")

    await browser.navigate("https://www.douyin.com")

    input("按回车键保存 Cookie 并关闭浏览器...")

    await browser.save_cookies()
    await browser.close()
    click.echo("\nCookie 已保存！后续爬取将自动使用这些 Cookie。")


@cli.command()
@click.argument("keyword")
@click.option("--max-count", "-n", default=50, help="最大爬取数量")
@click.option("--sort", "-s", type=click.Choice(["综合", "最新", "最热"]), default="综合")
@click.option("--type", "search_type", type=click.Choice(["video", "user"]), default="video")
@click.option("--publish-time", type=click.Choice(["0", "1", "7", "182"]), default="0",
              help="发布时间预设范围: 0=不限 1=一天内 7=一周内 182=半年内")
@click.option("--start-date", help="自定义起始日期 (含当天), 格式 YYYY-MM-DD, 仅对 video 生效")
@click.option("--end-date", help="自定义结束日期 (含当天), 格式 YYYY-MM-DD, 仅对 video 生效")
@click.option("--feishu-table", help="飞书表格 table_id（不指定则用 .env 配置或本地存储）")
@click.option("--local", "save_local", is_flag=True, help="同时保存到本地 CSV")
def search(keyword, max_count, sort, search_type, publish_time, start_date, end_date, feishu_table, save_local):
    """按关键词搜索抖音视频或用户"""
    sort_map = {"综合": 0, "最新": 1, "最热": 2}
    # Validate date inputs early (before opening any network session).
    try:
        DateFilter.from_inputs(publish_time, start_date, end_date)
    except ValueError as e:
        raise click.UsageError(str(e))
    if search_type == "user" and (start_date or end_date or publish_time != "0"):
        click.echo("提示: 日期过滤仅对视频搜索 (--type video) 生效，用户搜索将忽略。")
    asyncio.run(
        _search(keyword, max_count, sort_map[sort], search_type,
                publish_time, start_date, end_date, feishu_table, save_local)
    )


async def _search(keyword, max_count, sort_type, search_type,
                  publish_time, start_date, end_date, feishu_table, save_local):
    async with DouyinClient(cookies=DOUYIN_COOKIE) as client:
        scraper = KeywordScraper(client)

        if search_type == "video":
            results = await scraper.search_videos(
                keyword, max_count, sort_type,
                publish_time=publish_time, start_date=start_date, end_date=end_date,
            )
            records = [video_to_feishu_record(v) for v in results]
            _output(records, feishu_table, save_local, f"search_videos_{keyword}", "video")
        else:
            results = await scraper.search_users(keyword, max_count)
            records = [user_to_feishu_record(u) for u in results]
            _output(records, feishu_table, save_local, f"search_users_{keyword}", "user")


@cli.command()
@click.argument("url")
@click.option("--max-videos", "-n", default=50, help="最大视频爬取数量")
@click.option("--info-only", is_flag=True, help="仅获取用户信息，不爬取视频列表")
@click.option("--feishu-table", help="飞书表格 table_id")
@click.option("--local", "save_local", is_flag=True, help="同时保存到本地 CSV")
def user(url, max_videos, info_only, feishu_table, save_local):
    """从作者主页链接爬取用户信息和视频列表"""
    asyncio.run(_user(url, max_videos, info_only, feishu_table, save_local))


async def _user(url, max_videos, info_only, feishu_table, save_local):
    async with DouyinClient(cookies=DOUYIN_COOKIE) as client:
        scraper = UserScraper(client)

        user_info = await scraper.get_user_info(url)
        if user_info:
            click.echo(f"\n用户: {user_info.nickname}")
            click.echo(f"粉丝: {user_info.follower_count} | 关注: {user_info.following_count}")
            click.echo(f"获赞: {user_info.total_favorited} | 作品: {user_info.aweme_count}")
            click.echo(f"简介: {user_info.signature}\n")

            user_records = [user_to_feishu_record(user_info)]
            _output(user_records, feishu_table, save_local, f"user_{user_info.nickname}", "user")

        if not info_only:
            videos = await scraper.get_user_videos(url, max_videos)
            if videos:
                records = [video_to_feishu_record(v) for v in videos]
                _output(records, feishu_table, save_local, f"user_videos_{user_info.nickname if user_info else 'unknown'}", "video")


@cli.command()
@click.argument("aweme_id")
@click.option("--comments", "-c", is_flag=True, help="同时爬取评论")
@click.option("--max-comments", "-n", default=100, help="最大评论爬取数量")
@click.option("--feishu-table", help="飞书表格 table_id")
@click.option("--local", "save_local", is_flag=True, help="同时保存到本地 CSV")
@click.option("--headless/--no-headless", default=True)
def video(aweme_id, comments, max_comments, feishu_table, save_local, headless):
    """获取视频详情（可选：爬取评论）"""
    asyncio.run(_video(aweme_id, comments, max_comments, feishu_table, save_local, headless))


async def _video(aweme_id, comments, max_comments, feishu_table, save_local, headless):
    async with DouyinBrowser() as browser:
        await browser.start(headless=headless)
        scraper = VideoScraper(browser)

        detail = await scraper.get_video_detail(aweme_id)
        if detail:
            click.echo(f"\n视频: {detail.get('desc', '')}")
            stats = detail.get("statistics", {})
            click.echo(
                f"播放: {stats.get('play_count', 0)} | "
                f"点赞: {stats.get('digg_count', 0)} | "
                f"评论: {stats.get('comment_count', 0)}"
            )

        if comments:
            comment_list = await scraper.get_comments(aweme_id, max_comments)
            if comment_list:
                records = [comment_to_feishu_record(c) for c in comment_list]
                _output(records, feishu_table, save_local, f"comments_{aweme_id}", "comment")


@cli.command()
@click.option("--feishu-table", help="飞书表格 table_id")
@click.option("--local", "save_local", is_flag=True, help="同时保存到本地 CSV")
@click.option("--headless/--no-headless", default=True)
def trending(feishu_table, save_local, headless):
    """获取抖音热搜榜"""
    asyncio.run(_trending(feishu_table, save_local, headless))


async def _trending(feishu_table, save_local, headless):
    async with DouyinBrowser() as browser:
        await browser.start(headless=headless)
        scraper = TrendingScraper(browser)
        items = await scraper.get_hot_search()

        if items:
            click.echo(f"\n抖音热搜榜 (共 {len(items)} 条):\n")
            for item in items[:10]:
                click.echo(f"  {item.rank}. {item.title} (热度: {item.hot_value})")
            if len(items) > 10:
                click.echo(f"  ... 共 {len(items)} 条\n")

            records = [trending_to_feishu_record(t) for t in items]
            _output(records, feishu_table, save_local, "trending", "trending")


def _folder_token(value: str) -> str:
    """Accept a raw folder token or a full Feishu folder URL, return the token."""
    if not value:
        return ""
    value = value.strip().rstrip("/")
    if "/folder/" in value:
        value = value.split("/folder/")[-1]
    # strip any query string
    return value.split("?")[0]


@cli.command(name="scrape-to-bitable")
@click.argument("keyword")
@click.option("--folder", help="飞书文件夹 token 或 URL（新建多维表格的位置；留空建在应用空间）")
@click.option("--name", default="抖音作品数据", help="新建多维表格的名称")
@click.option("--publish-time", type=click.Choice(["0", "1", "7", "182"]), default="0",
              help="发布时间预设范围: 0=不限 1=一天内 7=一周内 182=半年内")
@click.option("--start-date", help="自定义起始日期 (含当天) YYYY-MM-DD")
@click.option("--end-date", help="自定义结束日期 (含当天) YYYY-MM-DD")
@click.option("--min-engagement", type=int, default=0,
              help="互动过滤阈值：点赞/收藏/评论需 > 此值（0=不过滤）")
@click.option("--engagement-logic", type=click.Choice(["or", "and"]), default="or",
              help="互动过滤的逻辑：or=任一指标达标，and=全部达标")
@click.option("--max-posts", type=int, default=0, help="最多保留的作品总数（0=不限，视频+图文交替）")
@click.option("--no-comments", is_flag=True, help="只抓作品(视频+图文)，跳过一/二级评论")
@click.option("--headed", is_flag=True, help="用可见的本地浏览器代替无头浏览器（无头总崩溃时用）")
@click.option("--ui-comments", is_flag=True, help="用模拟点击(真人登录态)抓评论，含二级评论(自动启用 headed)")
@click.option("--structure-only", is_flag=True, help="只新建 4 张表结构，不抓数据")
def scrape_to_bitable(keyword, folder, name, publish_time, start_date, end_date,
                      min_engagement, engagement_logic, max_posts, no_comments, headed, ui_comments, structure_only):
    """新建标准 4 表多维表格(视频作品/图文作品/一级评论/二级评论)并跑完整流程写入。

    作品的封面/视频/图片以真实文件上传为附件；作品链接、作者主页为链接原文。
    建好后可复用：在 .env 设置返回的 app_token 与各 table_id。
    """
    try:
        DateFilter.from_inputs(publish_time, start_date, end_date)
    except ValueError as e:
        raise click.UsageError(str(e))
    asyncio.run(_scrape_to_bitable(
        keyword, _folder_token(folder), name,
        publish_time, start_date, end_date,
        min_engagement, engagement_logic, max_posts, no_comments, headed, ui_comments, structure_only,
    ))


async def _scrape_to_bitable(keyword, folder_token, name,
                             publish_time, start_date, end_date,
                             min_engagement, engagement_logic, max_posts,
                             no_comments, headed, ui_comments, structure_only):
    # 1. Create the canonical 4-table bitable
    feishu = FeishuBitable()
    try:
        ids = feishu.create_full_bitable(name, folder_token)
    except RuntimeError as e:
        msg = str(e)
        click.echo(f"新建多维表格失败: {msg}")
        if "DriveNodePermNotAllow" in msg or "1254701" in msg:
            click.echo("原因: 自建应用对该文件夹没有写入权限。")
            click.echo("请在飞书里打开该文件夹 → 右上角「...」/共享 → 添加你的自建应用为协作者并授予「可编辑」，")
            click.echo("并确认应用已开通 drive:drive (云空间) 与 bitable:app 权限且已发布版本。")
        feishu.close()
        return
    feishu.close()

    # 2. Run the full pipeline into those tables (unless structure-only).
    #    scrape_all reads its table ids / keyword / filter from module globals
    #    at call time, so we set them before invoking its main().
    if not structure_only:
        import scrape_all
        scrape_all.APP_TOKEN = ids["app_token"]
        scrape_all.KEYWORD = keyword
        scrape_all.VIDEO_TABLE_ID = ids["video_table_id"]
        scrape_all.IMAGE_TABLE_ID = ids["image_table_id"]
        scrape_all.COMMENT_L1_TABLE_ID = ids["comment_l1_table_id"]
        scrape_all.COMMENT_L2_TABLE_ID = ids["comment_l2_table_id"]
        scrape_all.DATE_FILTER = DateFilter.from_inputs(publish_time, start_date, end_date)
        scrape_all.SKIP_COMMENTS = no_comments
        scrape_all.MIN_ENGAGEMENT = min_engagement
        scrape_all.ENGAGEMENT_LOGIC = engagement_logic
        scrape_all.MAX_POSTS = max_posts
        if headed or ui_comments:
            scrape_all.HEADLESS = False   # UI clicks need a real/headed browser
        if ui_comments:
            scrape_all.USE_UI_COMMENTS = True
        await scrape_all.main()

    click.echo("\n=== 多维表格已就绪 ===")
    click.echo(f"链接      : {ids['url']}")
    click.echo(f"app_token : {ids['app_token']}")
    click.echo(f"视频作品  : {ids['video_table_id']}")
    click.echo(f"图文作品  : {ids['image_table_id']}")
    click.echo(f"一级评论  : {ids['comment_l1_table_id']}")
    click.echo(f"二级评论  : {ids['comment_l2_table_id']}")
    click.echo("复用方法  : 在 .env 设置 FEISHU_APP_TOKEN / VIDEO_TABLE_ID / IMAGE_TABLE_ID / "
               "COMMENT_L1_TABLE_ID / COMMENT_L2_TABLE_ID 为以上值。")


@cli.command()
@click.option("--type", "table_type",
              type=click.Choice(["video", "image", "comment-l1", "comment-l2", "user", "trending"]),
              required=True)
@click.option("--table-id", required=True, help="飞书表格 table_id")
def setup_feishu(table_type, table_id):
    """初始化飞书多维表格的字段结构"""
    feishu = FeishuBitable()
    setup_map = {
        "video": feishu.setup_video_table,
        "image": feishu.setup_image_table,
        "comment-l1": feishu.setup_comment_l1_table,
        "comment-l2": feishu.setup_comment_l2_table,
        "user": feishu.setup_user_table,
        "trending": feishu.setup_trending_table,
    }
    setup_map[table_type](table_id)
    click.echo(f"已初始化 {table_type} 类型的表格字段结构")
    feishu.close()


def _output(records, feishu_table, save_local, name, data_type):
    if not records:
        click.echo("没有数据可输出。")
        return

    if feishu_table or FEISHU_APP_ID:
        try:
            feishu = FeishuBitable()
            table_id = feishu_table or ""
            feishu.write_records(records, table_id)
            feishu.close()
        except Exception as e:
            click.echo(f"飞书写入失败: {e}，回退到本地存储")
            save_local = True

    if save_local or not FEISHU_APP_ID:
        local = LocalStorage()
        local.save_csv(records, f"{name}.csv")
        local.save_json(records, f"{name}.json")


if __name__ == "__main__":
    cli()
