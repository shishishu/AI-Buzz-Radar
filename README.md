# AI Buzz Radar

一个极简的 Product Hunt AI 产品信息流。每条动态保留发布日期、主要变化、为什么值得看，以及 Product Hunt 原文入口。

## 本地运行

需要 Python 3.12 和 [uv](https://docs.astral.sh/uv/)。

```bash
uv sync --locked --python 3.12
uv run --locked radar serve
```

打开 [本地信息流](http://127.0.0.1:8000/)。服务从 SQLite 读取已收录的动态，首个版本会将旧的公共简报导入信息流。数据库默认位于 `data/product-hunt.sqlite3`，可用 `radar --db PATH` 或 `RADAR_DB` 指定。

## 生成与更新

后台使用 OpenAI Responses API 的 `gpt-6.2-sol`、`high` 推理档位和托管网页搜索。配置 `OPENAI_API_KEY` 后，可以手动更新或启动每日任务。CLI 也可从被 Git 忽略的 `.env.local` 读取凭据。

```bash
uv run --locked radar run --budget-usd 1.00
uv run --locked radar daily --hour 21 --budget-usd 1.00
```

每日任务默认北京时间 21:00 运行，每天最多自动尝试一次，进程重启后仍使用 SQLite 的运行记录。已有条目会持续显示。手动的 `run --day YYYY-MM-DD` 可以指定日期，`--force` 可以授权同一天再研究一次。默认窗口是当天和前两天，`--days 4` 可回补前三天。

Agent 优先查当天 Product Hunt 站内榜单和 AI 主题，核验具体发布页面与日期。历史发布只用于补漏。根据上线日期排序，同一天沿用 Agent 给出的顺序。发布标识或同日规范化标题相同的条目只收录一次。 [Responses 网页搜索](https://developers.openai.com/api/docs/guides/tools-web-search)

## 匿名阅读记录

浏览器使用随机 HttpOnly Cookie，SQLite 记录 Cookie 哈希派生的匿名 ID。站内记录首页浏览、卡片至少一半进入视口，以及点击 Product Hunt 原文。用户、条目、行为和时间均独立保存，为未来的「已读、关注主题、降低重复和反馈」保留关联字段。信息流当前按时间统一排序。

## 账本

```bash
uv run --locked radar usage
uv run --locked radar request REQUEST_ID
uv run --locked radar show
```

持续记录请求输入、API 响应与 ID、网页工具动作、token 用量和费用。流式请求增加 `ttft_ms` 和 `tpot_ms`。TTFT 从发出请求计至首段非空正文，TPOT 使用首尾正文分片之间的时间与 API 返回的非推理输出 token 数估算。旧请求和缺少计时条件的请求保留空值。 [OpenAI 流式响应](https://developers.openai.com/api/docs/guides/streaming-responses) · [NVIDIA 延迟指标](https://docs.nvidia.com/nim/benchmarking/llm/1.0.0/metrics)

累计估算预算默认为每库 $1，可用 `RADAR_BUDGET_USD` 或 `--budget-usd` 调整。默认请求预留 $0.49。`--compact` 将工具调用限制为两次，输出限制为 1,600 token，预留 $0.3685。收到用量后按公开费率结算。缺少用量的请求保留预留额度，SDK 自动重试已关闭。网页工具动作费用采用保守估算，实际账单以 Platform 为准。 [API 定价](https://developers.openai.com/api/docs/pricing) · [缓存计费](https://developers.openai.com/api/docs/guides/prompt-caching)

## 测试和部署

```bash
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked python -m unittest discover -s tests -v
```

离线测试涵盖站内证据、回补与去重、旧简报迁移、匿名事件、流式计时和预算拦截。部署时，Web 和每日任务共享同一个 SQLite 卷。Web 服务监听宿主机的 `127.0.0.1:8000`，每日任务从部署环境读取 API 密钥。

2026-11-22 的首次信息流实测因具体发布页证据不足被拦截。紧凑重试重新核验候选后收录了 Omi CLI。重试 TTFT 为 18.41 秒，TPOT 估算为 7.85 ms/token，单次费用 $0.0686995。同一数据库的全部实测累计估算为 $0.6986572。 [Omi CLI 的 Product Hunt 发布页](https://www.producthunt.com/products/omi-cli)

```bash
docker compose up -d --build web
docker compose --profile daily up -d --build
```
