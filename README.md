# AI Buzz Radar

面向设计、开发、评估和维护智能体的读者。每天精选三篇一手材料，既可以是解释模型行为的论文，也可以是帮助开发者做决定的技术解析、开发指南或生产复盘。中英文页面均保留出版方原题。标题下的「推荐理由」说明谁值得读、能用它做什么决定。「内容摘要」先给结论，再说明方法和证据，并优先选用出版方原文中的配图。点击原图可放大，图注链接回原文章节。「延伸思考」讨论工程取舍和验证方法。11 月 25 日起，双语页面默认中文；页首可切换 English，带有 `?lang=en` 的链接可直接进入英文版。「原文章节」定位到小节，「定位原句」使用浏览器文本片段。中文页在出版方提供译文时显示「官方中文译文」，英文页直接链接原文。[打开最新日报](examples/index.html)

## 运行日报

需要 Python 3.12 和 uv。仓库附有可离线浏览的 Markdown、HTML 和结构化存档。只查看日报无需 API Key。

```bash
uv sync --locked --python 3.12
python3 -m http.server 8765 --bind 127.0.0.1 --directory examples
```

浏览器打开 [本地日报](http://127.0.0.1:8765/)。首页只列最新三篇，历史数据用于区分「首次入选」「连续入选」「再度入选」。连续留选显示第几天，已分享的日期链接仍可直达。页面、样式和表格均支持离线打开。原文定位优先使用出版方的章节锚点，缺少锚点时使用浏览器文本片段。

### 每日选稿与记录

日报使用本机已登录的 Codex CLI（`gpt-6.2-astra`，`ultra`）。提示词、候选来源、排序规则、原文引证校验、双语模板和选稿记录格式都随仓库版本保存。每次执行从指定日期和一手来源开始，手动和定时出刊使用同一套流程。

```bash
uv run --locked radar edition --output examples
uv run --locked radar selection --day 2026-11-25 --format markdown
```

在有 systemd 用户管理器的 Linux 主机执行以下命令安装定时器。定时器每天北京时间 21:00 触发一次，日报进程写完后退出。主机停机错过触发时，恢复后补最近到期的一期。已完整出刊的日期直接验收。生成失败时每隔 15 分钟重试，最多运行三次。持续使用的主机应让用户管理器在登出后继续运行，可用 `loginctl show-user "$USER" -p Linger` 查看。

```bash
.venv/bin/python scripts/install_edition_timer.py
systemctl --user list-timers ai-buzz-radar-edition.timer
journalctl --user -u ai-buzz-radar-edition.service -n 30
```

成功后首页位于 `examples/index.html`，当期结构化稿件在 `examples/editions/`。每日的 JSON 和可读 Markdown 写入网页目录外的 `selection-records/`。失败记录在 `selection-records/attempts/`，逐次模型调用和原文快照保存在私有的 `selection-records/.radar-runs/`。同日重试可复用已经通过校验的步骤。发布前会核对实际渲染的中英文栏目、阅读链接、原图与稿件顺序，再安装新首页。

- **召回**汇集近 30 天的 arXiv 论文及 Anthropic、Lil’Log、LangChain、Hugging Face、OpenAI、Cloudflare 的一手文章。记录查询范围、来源、抓取告警、候选标题、日期和链接。arXiv 的标题检索按相关性最多取 80 条，快照受源站覆盖和返回上限影响。
- **粗排**分两路提名，一路读 arXiv 索引，另一路读一手网站索引，后者包括技术博客、生产复盘和研究团队发布的文章。每个来源最多送审 80 条。两路都按材料能否回答具体问题提名，可以提名零篇。按各路优先顺序交替取稿，合并后最多精读 12 篇。若一路只有两篇值得精读，另一路可以补足十篇。记录分别列出两路召回、进入精读名单和最终入选的数量。
- **精排**把两路的原文节选放在一起，逐篇辨认主要体裁，判断它的证据能支持开发者做什么决定。论文可以用消融和基线支撑判断，指南可以用可复核的实现说明取舍，复盘可以用故障轨迹解释机制。只有单个跑分或功能介绍的文章优先级低。三席综合考虑证据、开发价值和问题的互补程度。质量相当时，优先保留能提供不同阅读体验的组合。记录保存组合理据、原文引证和候补递补情况。往期入选信息在出稿时生成标签。
- **成稿与配图**生成推荐理由、内容摘要和延伸思考，用同一份原文快照核对引文，再渲染中文和英文版。优先选择能支持摘要的出版方原图。arXiv 原始矢量图可等比转为 PNG。两路原图均记录出处和指纹，缺少可核实的合适图时，私有选稿记录会说明原因。

编辑可传入三个 `--pick URL` 指定当期选题，记录会标明人工指定的顺序及核验结果。对已有日期重新选稿可用 `radar edition --day YYYY-MM-DD --reselect`。新记录链接至上一版的选稿材料和稿件。日常运行默认使用本地 Codex 登录账号，`--engine responses` 可显式选择旧接口，`--budget-usd` 适用于该接口的累计预算。[11 月 25 日筛选漏斗](selection-records/2026-11-25.md)

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
