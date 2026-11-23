# AI Buzz Radar

面向程序员的 Agent 系统日报。每期三篇技术文章，可在首页用一分钟扫读结论和推荐理由，再逐篇展开 Summary 与 Thinking。前者梳理机制与证据，后者讨论工程取舍和验证方法。十五分钟是含原文选段的整篇阅读估时。原文定位链接、对照表和完整原文放在相应文章下。[打开最新日报](examples/index.html)

## 运行日报

需要 Python 3.12 和 uv。仓库附有可离线浏览的 Markdown、HTML 和结构化存档。只查看日报无需 API Key。

```bash
uv sync --locked --python 3.12
python3 -m http.server 8765 --bind 127.0.0.1 --directory examples
```

浏览器打开 [本地日报](http://127.0.0.1:8765/)。右上角的「往期日报」可按日期切换。页面、样式和表格均支持离线打开。原文定位优先使用出版方的章节锚点，缺少锚点时使用浏览器文本片段。

### 生成与存档

```bash
uv run --locked radar edition --day 2026-11-23 --output examples --budget-usd 4
uv run --locked radar edition --daily --hour 21 --output examples --budget-usd 4
uv run --locked radar usage
uv run --locked radar request REQUEST_ID
```

第一条命令生成指定日期的一期，默认日期为上海当地当天。已存档日期可离线重新渲染。第二条启动持续运行的日报进程，默认北京时间 21:00 出刊。预算是同一 SQLite 账本的累计美元上限，跨日期、跨命令共享。浏览和重新渲染不产生 API 消耗。

来源包括 Anthropic Engineering、Anthropic Research、Lil’Log、Hugging Face、OpenAI 和 Cloudflare 的一手文章。程序读取各来源当前索引中的日期和标题，按日报日期截断。Responses API 根据技术相关性、机制、实验及失败分析给出候选顺序，优先采用近 30 天、从未收录的文章。可从近 90 天候选和历史已核实文章补读，页面会标记超窗或上次收录日期。冷启动时若没有三篇合格原文，保留原版首页，返回生成失败。回溯旧日期时，当前索引可能无法完整重建当天的候选池。

编辑可用三个 `--pick URL` 指定当期选题，仍需通过来源、日期、原文证据和数量校验。每篇由 `gpt-6.2-sol` 的 `high` 推理生成，三段解读分别核验原文摘录，证据通过才发布整期。图表由原文重新整理。档案目录 `editions/YYYY-MM-DD.json` 内含每篇的请求 ID。旁边的 Markdown 是正文，HTML 由同一份 Markdown 转换。账本记录实际模型输入、响应、原文页、token、缓存读写、TTFT、TPOT 和估算费用。

### 本地 Codex CLI 对照

11 月 21、22 日回填时指定了编辑选题，11 月 23 日启用自动选题。后者可用来对照两种运行方式。[Responses API 样例](examples/agent-reading-2026-11-23.html) · [本地 Codex CLI 样例](examples/codex-cli/agent-reading-2026-11-23.html)

```bash
uv run --locked python scripts/compare_edition.py --day 2026-11-23
```

复现实验需要当天的原始 API 账本和已登录的本地 Codex CLI。脚本从选题请求重放候选目录、前期收录日期及筛选要求。CLI 使用 `gpt-6.2-sol / high` 独立排序和解读。两边同时选中的文章使用相同的编号原文节选，模型只读取目录或原文材料。新选入的文章从白名单内的一手来源获取。两版共用证据校验和 Markdown 转 HTML 模板。CLI 运行事件、用量、输入与结果保存在数据库旁的 `cli-comparisons/` 目录，以 CLI 会话 ID 关联。样例中的 API 版经过编辑复核和改版，适合逐篇比较覆盖与取舍。

### 早期阅读清单实验

`radar blogs` 保留早期多轮工具调用的 Markdown 对照实验，使用 Anthropic 和 Lil’Log 目录。每日三篇 HTML 的入口是 `radar edition`。

## Product Hunt 本地网页

需要 Python 3.12 和 [uv](https://docs.astral.sh/uv/)。

```bash
uv sync --locked --python 3.12
uv run --locked radar serve
```

本地网页从 SQLite 读取已发布的一期日报。数据库默认位于 `data/product-hunt.sqlite3`，可用 `radar --db PATH` 或 `RADAR_DB` 指定。 [打开本地信息流](http://127.0.0.1:8000/)

## 生成与更新

后台使用 OpenAI Responses API 的 `gpt-6.2-sol`、`high` 推理档位和托管网页搜索。配置 `OPENAI_API_KEY` 后，可以手动更新或启动每日任务。CLI 也可从被 Git 忽略的 `.env.local` 读取凭据。

```bash
uv run --locked radar run --budget-usd 1.00
uv run --locked radar daily --hour 21 --budget-usd 1.00
```

每日任务默认北京时间 21:00 运行，每天最多自动尝试一次，进程重启后仍使用 SQLite 的运行记录。手动的 `run --day YYYY-MM-DD` 可以指定日期，`--force` 可以在同一天再研究一次。默认窗口是当天和前两天，`--days 4` 可回补前三天。

Agent 依次检查 Product Hunt 当天日榜前 20 个有编号的条目。发布页需要明确说明核心 AI 能力、Agent、专为模型或 Agent 设计的工具，或本次发布中的实质 AI 更新。只有分类标签或笼统宣传的条目跳过。日报选出前三个符合条件的发布并保留各自的原名次。当日不足三条时，从近两天按日期和原名次去重补齐，标记原发布日期。仍不足时继续展示上一期。 [Responses 网页搜索](https://developers.openai.com/api/docs/guides/tools-web-search)

卡片直接显示一句话概述和发布页事实摘要。经过核对且能解释产品功能的发布图、产品信息表或发布页链接的 YouTube 演示可在卡片内展开。视频在展开时加载。

也可以用 `radar run --day YYYY-MM-DD --force --snapshot PATH` 验证已核对的官方日榜快照。JSON 包含 `day`、`source_url` 和 `entries`。每条包含 `source_rank`、`title`、`launch_url` 和来自发布页的 `evidence`，可附 `facts`（`label`、`value`）和 `media`（`url`、`caption`）。此模式固定日榜原名次，模型负责筛选并总结发布内容。

## 匿名阅读记录

浏览器使用随机 HttpOnly Cookie，SQLite 记录 Cookie 哈希派生的匿名 ID。站内记录首页浏览、卡片至少一半进入视口，以及点击 Product Hunt 原文。用户、条目、行为和时间均独立保存，为未来的「已读、关注主题、降低重复和反馈」保留关联字段。

## 账本

```bash
uv run --locked radar usage
uv run --locked radar request REQUEST_ID
uv run --locked radar show
```

持续记录请求输入、API 响应与 ID、网页工具动作、token 用量和费用。流式请求增加 `ttft_ms` 和 `tpot_ms`。TTFT 从发出请求计至首段非空正文，TPOT 使用首尾正文分片之间的时间与 API 返回的非推理输出 token 数估算。旧请求和缺少计时条件的请求保留空值。 [OpenAI 流式响应](https://developers.openai.com/api/docs/guides/streaming-responses) · [NVIDIA 延迟指标](https://docs.nvidia.com/nim/benchmarking/llm/1.0.0/metrics)

累计估算预算默认为每库 $1，可用 `RADAR_BUDGET_USD` 或 `--budget-usd` 调整。默认请求预留 $0.49，`--compact` 预留 $0.3685。使用已核对的快照时，模型请求只处理快照文本，预留 $0.0885。收到用量后按公开费率结算。缺少用量的请求保留预留额度，SDK 自动重试已关闭。网页工具动作费用采用保守估算，实际账单以 Platform 为准。 [API 定价](https://developers.openai.com/api/docs/pricing) · [缓存计费](https://developers.openai.com/api/docs/guides/prompt-caching)

## 测试和部署

```bash
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked python -m unittest discover -s tests -v
```

离线测试涵盖站内证据、回补与去重、旧简报迁移、匿名事件、流式计时和预算拦截。部署时，Web 和每日任务共享同一个 SQLite 卷。Web 服务监听宿主机的 `127.0.0.1:8000`，每日任务从部署环境读取 API 密钥。

2026-11-22 的实测使用已核对的日榜前五名快照，最终发布 #1 Rankhog、#2 Yoroll 和 #3 Resurf。输入 1,584 tokens，输出 607，缓存读取 0，缓存写入 1,581。TTFT 为 3.78 秒，TPOT 估算为 9.98 ms/token，本次估算费用 $0.0100285。同一数据库的实测累计估算为 $0.7151417。 [Product Hunt 当天日榜](https://www.producthunt.com/leaderboard/daily/2026/11/22)

```bash
docker compose up -d --build web
docker compose --profile daily up -d --build
```
