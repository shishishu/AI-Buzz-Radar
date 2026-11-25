# AI Buzz Radar

每天用三篇一手研究，回答三个关于 Agent 能力的问题。面向对智能体好奇的读者和开发人员，优先考虑 arXiv 论文、研究团队的技术报告和博客。折叠卡的「核心看点」第一句直接给出发现，第二句交代支撑它的观察或对照。「内容摘要」解释作者怎样得出结论，附原文证据和合适的出版方原图。「延伸思考」指出结论在哪些条件下成立，以及可以怎样验证。

页面默认中文，可切换 English，也可通过 `?lang=en` 分享英文版。两种语言都保留出版方原题，文末只有「阅读原文」一个入口。段落中的证据链接可定位到原文小节或原句，图片可点击放大。[打开最新日报](examples/index.html)

## 运行日报

需要 Python 3.12 和 uv。仓库附有可离线浏览的 Markdown、HTML 和结构化存档。只查看日报无需 API Key。

```bash
uv sync --locked --python 3.12
python3 -m http.server 8765 --bind 127.0.0.1 --directory examples
```

每篇文章使用独立卡片，默认读到核心看点。点击卡片可在原位展开，再点即可收起。原文链接和图片可单独打开。[本地日报](http://127.0.0.1:8765/)

首页只列最新三篇，历史数据用于区分「首次入选」「连续入选」「再度入选」。连续留选显示第几天，已分享的日期链接仍可直达。页面、样式和表格均支持离线打开。原文定位优先使用出版方的章节锚点，缺少锚点时使用浏览器文本片段。

对外分享使用 [GitHub Pages 日报首页](https://shishishu.github.io/radar/)。开发机定时生成并核验三篇稿件，随后通过 Git 将首页和本期 HTML 发布到个人站点仓库的 `radar/` 目录。日期链接可长期分享。定时任务会检查两个线上页面是否与本地稿件一致；重试会复用已验收的稿件。开发机需要保持可运行，并为定时任务的系统用户配置个人站点仓库的 Git 推送权限。网页由 GitHub Pages 提供，读者访问无需连接开发机。

### 每日选稿与记录

日报使用本机已登录的 Codex CLI（`gpt-6.2-astra`，`ultra`）。提示词、候选来源、排序规则、原文引证校验、双语模板和选稿记录格式都随仓库版本保存。每次执行从指定日期和一手来源开始，手动和定时出刊使用同一套流程。

```bash
uv run --locked radar edition --output examples
uv run --locked radar selection --day 2026-11-25 --format markdown
```

在有 systemd 用户管理器的 Linux 主机执行以下命令安装定时器。定时器每天北京时间 09:00 触发一次，日报进程写完后退出。主机停机错过触发时，恢复后补最近到期的一期。已完整出刊的日期直接验收。生成失败时每隔 15 分钟重试，最多运行三次。持续使用的主机应让用户管理器在登出后继续运行，可用 `loginctl show-user "$USER" -p Linger` 查看。

```bash
.venv/bin/python scripts/install_edition_timer.py
systemctl --user list-timers ai-buzz-radar-edition.timer
journalctl --user -u ai-buzz-radar-edition.service -n 30
```

成功后首页位于 `examples/index.html`，当期结构化稿件在 `examples/editions/`。每日的 JSON 和可读 Markdown 写入网页目录外的 `selection-records/`。失败记录在 `selection-records/attempts/`，逐次模型调用和原文快照保存在私有的 `selection-records/.radar-runs/`。同日重试可复用已经通过校验的步骤。发布前会核对实际渲染的中英文栏目、阅读链接、原图与稿件顺序，再安装新首页。

- **召回**以近 30 天的一手研究为主，从 arXiv、METR、Replit Frontier、Anthropic、OpenAI、LangChain 等来源找候选。记忆、长程任务、递归自我改进只是检索入口，其他主题也可以入选。经典回溯最远至 90 天，记录原始发表日与近 30 天的新讨论，分别检查。程序从 Hacker News 和 Hugging Face Papers 的可核查评论里寻找线索，保留发言时间、原话和链接。索引覆盖、请求上限和抓取失败都会影响当期能看到的信号。
- **粗排**将 arXiv 和一手网站分开提名，每个来源最多送审 80 条元数据。提名要说清楚原文值得查证的问题。两路按各自的优先顺序交替进入精读，一路名额可由另一路补足，合计最多 12 篇。记录保存渠道数量和逐项取舍。
- **精排**先核对原文证据，再按问题重要性（30）、证据质量（30）、知识增量（20）、时效性（10）、有据可查的讨论（10）给分，记录内部前五及合格候选的缺额。无可核查的讨论时，该项记零。选公开三席时再考虑每篇能给读者增加哪个独立判断，记下强候补让位的理由。最终稿件、原文证据、写作失败与递补顺序都留在生成主机的选稿记录中。
- **成稿与配图**写作接收该篇精排留下的读者价值，用原文核实并限定适用范围。先写内容摘要和延伸思考，再从中提炼一项可核查的发现和支撑它的证据，放入折叠卡的核心看点。两种语言均以同一份原文快照核对引文。优先选择能支持摘要的出版方原图。arXiv 原始矢量图可等比转为 PNG。两路原图均记录出处和指纹，缺少可核实的合适图时，私有选稿记录会说明原因。

编辑可传入三个 `--pick URL` 指定当期选题，记录会标明人工指定的顺序及核验结果。对已有日期重新选稿可用 `radar edition --day YYYY-MM-DD --reselect`。新记录链接至上一版的选稿材料和稿件。日常运行默认使用本地 Codex 登录账号，`--engine responses` 可显式选择旧接口，`--budget-usd` 适用于该接口的累计预算。可在生成日报的主机运行上面的 `radar selection` 命令阅读当天的筛选漏斗。

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
uv run --locked playwright install chromium
uv run --locked python tests/browser/edition_focus.py
```

离线测试涵盖站内证据、回补与去重、旧简报迁移、匿名事件、流式计时和预算拦截。部署时，Web 和每日任务共享同一个 SQLite 卷。Web 服务监听宿主机的 `127.0.0.1:8000`，每日任务从部署环境读取 API 密钥。

2026-11-22 的实测使用已核对的日榜前五名快照，最终发布 #1 Rankhog、#2 Yoroll 和 #3 Resurf。输入 1,584 tokens，输出 607，缓存读取 0，缓存写入 1,581。TTFT 为 3.78 秒，TPOT 估算为 9.98 ms/token，本次估算费用 $0.0100285。同一数据库的实测累计估算为 $0.7151417。 [Product Hunt 当天日榜](https://www.producthunt.com/leaderboard/daily/2026/11/22)

```bash
docker compose up -d --build web
docker compose --profile daily up -d --build
```
