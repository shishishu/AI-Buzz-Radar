# AI Buzz Radar

一个极简的 Product Hunt AI 产品日报。首页的「今日 Top」显示原名次、产品名、一句话简介和 Product Hunt 原文。回补条目带原始发布日期。

## 本地运行

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

Agent 从 Product Hunt 当天日榜前 20 个有编号的条目开始，筛选核心功能依赖 AI 或有实质 AI 更新的发布。每条都需要当天日榜和具体站内发布页的证据。先按原名次选当天前三条，只有新增用途时才加入第 4、5 条。当日不足三条时，按日期和原名次从近期补到三条。仍不足时保留上一期及其日期。旧数据继续可在账本和已收录条目中查阅。 [Responses 网页搜索](https://developers.openai.com/api/docs/guides/tools-web-search)

也可以用 `radar run --day YYYY-MM-DD --force --snapshot PATH` 验证已核对的官方日榜快照。JSON 包含 `day`、`source_url` 和 `entries`。每条包含 `source_rank`、`title`、`launch_url` 和来自发布页的 `evidence`。此模式把原名次固定在快照中，模型负责筛选与撰写一句话。

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

2026-11-22 的「今日 Top」实测用已核对的日榜前四名快照，最终发布 #1 Rankhog、#2 Yoroll 和 #3 Resurf。TTFT 为 4.27 秒，TPOT 估算为 10.57 ms/token，本次估算费用 $0.006456。同一数据库的全部实测累计估算为 $0.7051132。 [Product Hunt 当天日榜](https://www.producthunt.com/leaderboard/daily/2026/11/22)

```bash
docker compose up -d --build web
docker compose --profile daily up -d --build
```
