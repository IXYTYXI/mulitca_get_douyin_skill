# 小红书爬虫（mulitca_get_xhs_skill）

按关键词搜索小红书笔记并落盘。参考同仓库的抖音爬虫结构（config/settings、
core/browser、登录检测、cookies.json 优先级等），把同一套模式迁移到小红书。

**重点：如何正确设置小红书 Cookie 让爬虫正常执行。**

---

## 1. 安装

```bash
cd xhs
pip install -r requirements.txt
python -m playwright install chromium
```

## 2. 设置 Cookie（最关键的一步）

小红书的搜索接口需要**已登录**的 Cookie 才会返回数据。两种设置方式，任选其一：

### 方式 A：扫码登录，自动保存（推荐）

```bash
python main.py login
```

会打开一个可见浏览器，扫码登录后程序自动检测到 `web_session` 写入，
把整条 Cookie 同时保存到 `.env`（`XHS_COOKIE=`）和 `cookies.json`。

### 方式 B：手动复制整条 Cookie

1. Chrome 打开 <https://www.xiaohongshu.com> 并扫码登录
2. `F12` 打开开发者工具 → **Network(网络)** 面板
3. 刷新页面，点任意一条 `xiaohongshu.com` 的请求
4. 在 **Request Headers** 里找到 `Cookie:`，**整行复制**它的值
5. 复制 `.env.example` 为 `.env`，把值粘到 `XHS_COOKIE=` 后面（不要带 `Cookie:` 前缀）

```bash
cp .env.example .env
# 然后编辑 .env，填入 XHS_COOKIE=...
```

### 关键登录字段

| 字段          | 含义                                              | 缺失后果                     |
| ------------- | ------------------------------------------------- | ---------------------------- |
| `web_session` | **登录后才会写入**，是判定“已登录”的主要标志       | 未登录，接口返回空/被拦       |
| `a1`          | 设备指纹，未登录也有；缺失说明 Cookie 没复制全     | 请求异常、易触发验证码       |
| `webId`       | 设备/浏览器标识                                    | 同上                         |
| `gid`         | 会话相关                                           | 通常意味着 Cookie 过期       |

> 程序以 `web_session` 是否有值来判定登录态；`a1/webId/gid` 用于给出更精确的诊断。

### Cookie 优先级

`cookies.json`（`login` 命令保存）**优先于** `.env` 的 `XHS_COOKIE`。删掉
`cookies.json` 即回退到 `.env`。

## 3. 校验登录态

```bash
python main.py check
```

会打印诊断，例如：

```
✅ 检测到登录态字段: web_session
   辅助字段 存在: a1, webId, gid | 缺失: (无)
```

未登录 / 过期时会明确告知缺哪个字段，并给出重新获取 Cookie 的步骤，
**而不是静默返回空结果**（退出码非 0，方便脚本判断）。

## 4. 按关键词搜索笔记

```bash
python main.py search "护肤" -n 30
```

- `-n / --max-count`：最多抓取的笔记数（默认 30）
- `--no-headless`：用可见浏览器（命中验证码时手动过验证用）
- `--out`：自定义输出文件名（不含扩展名）

抓到的字段（落盘到 `output/search_notes_<关键词>.json` 和 `.csv`）：

`note_id`、`title`、`desc`、`note_type`、`author_nickname`、`author_user_id`、
`liked_count`（点赞）、`collected_count`（收藏）、`comment_count`（评论）、
`share_count`、`cover_url`、`note_url`（笔记链接）、`xsec_token`。

## 5. 签名机制（x-s / x-t）

小红书 Web 接口需要 `x-s` / `x-t` 等签名头。本项目**不手写签名算法**，而是采用
**真实浏览器渲染 + 拦截官方接口响应**的方案：

- 用 Playwright 打开已登录的小红书页面，导航到搜索结果页；
- 页面自身（小红书前端 JS）负责对 `/api/sns/web/v1/search/notes` 等请求完成
  `x-s/x-t` 签名并发出真实请求；
- 我们通过 Playwright 的 `response` 事件**拦截这些接口的 JSON 响应**取数，
  并配合滚动翻页加载更多。

这样做的好处：签名永远由官方最新前端生成，不会因为签名算法版本更新而失效，
且走真实用户路径，验证码更少、更稳定。若接口一条都没拦到，会兜底从页面注入的
`window.__INITIAL_STATE__` 里解析首屏数据。

## 6. 常见问题

- **返回空 / 抓不到数据**：先 `python main.py check` 确认 `web_session` 有值；
  过期就重新 `python main.py login`。
- **命中验证码/风控**：用 `--no-headless` 打开可见浏览器手动过验证，或调大 `.env`
  里的 `REQUEST_DELAY`、降低频率后重试。
- **需要用户提供的东西**：一份**有效的已登录小红书 Cookie**（含 `web_session`）。
  无登录态时无法验证抓取结果——这是小红书的反爬限制，必须先完成登录。

## 目录结构

```
xhs/
├── main.py                # CLI: login / check / search
├── config/settings.py     # Cookie、登录字段、请求参数
├── core/
│   ├── cookies.py         # Cookie 解析 + 登录态校验（与浏览器无关，可单测）
│   └── browser.py         # Playwright 浏览器管理 + Cookie 注入
├── scrapers/keyword.py    # 关键词搜索笔记（拦截官方接口取数）
├── models/data.py         # NoteInfo / UserInfo 数据模型
├── storage/local.py       # 本地 json/csv 落盘
├── requirements.txt
├── .env.example
└── README.md
```
