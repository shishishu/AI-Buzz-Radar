# AI Buzz Radar

用 OpenAI Responses API 研究 Product Hunt 上的新 AI 产品和开发工具。每期简报收录最多五条动态，包含发布日期、主要变化、值得关注的原因和可点击的 Product Hunt 发布页。

当前版本使用 `gpt-6.2-sol`、`high` 推理档位。每期只发出一次 Responses 请求，模型可以在该请求内决定搜索词、打开候选页面并筛选结果。

## 本地运行

需要 Python 3.12 和 [uv](https://docs.astral.sh/uv/)。已有的 `OPENAI_API_KEY` 可以通过当前 shell 提供。项目也支持从本地被 Git 忽略的 `.env.local` 读取。

```bash
uv sync --locked --python 3.12
uv run --locked radar run --budget-usd 1.00
uv run --locked radar show
uv run --locked radar usage
uv run --locked radar serve
```

公共简报默认查找最近三个 Product Hunt 发布日期。`run --day YYYY-MM-DD --days 3` 可以回查。已生成的日期会复用原简报，`--force` 会重新研究并在成功后更新。简报和请求记录保存在 `data/product-hunt.sqlite3`，可以用全局参数 `radar --db PATH` 指定文件。 [打开本地公共简报](http://127.0.0.1:8000/)

## 按需生成

在网页填写 Product Hunt 发布起止日期和可选主题。起止日期均包含在结果范围内。每次新提交生成独立结果，结果页可以打开请求追踪 JSON。同一个表单重复提交时会返回原请求。公共简报另有自己的生成入口。 [打开按需生成](http://127.0.0.1:8000/research)

首次打开按需页面时，服务给浏览器分配随机的 HttpOnly Cookie。数据库用该值的哈希作为匿名 `user_id`。同一浏览器能查看自己的请求，另一浏览器或清除 Cookie 后会获得新的匿名身份。

每个新生成请求用 `request_id` 保存选择条件、实际 API 请求体、OpenAI 响应和 HTTP 请求 ID、已返回的搜索词和打开页面、校验结果、用量与估算费用。工具轨迹字段以 API 返回为准。此前的公共简报和用量账本可继续读取。项目操作者也可以在终端查看追踪。

```bash
uv run --locked radar request REQUEST_ID
```

## Agent 如何工作

1. 公共简报从 SQLite 读取最近 14 天以去重，最多向模型传入 25 条历史路径。按需生成从指定日期和主题独立选题。
2. 模型在 OpenAI 托管的 `web_search` 工具中查阅 Product Hunt 榜单、主题和具体发布页。本地浏览器提交参数、展示结果。工具配置限定 `producthunt.com`，并用低搜索上下文、6 次工具调用参数和 6,500 个输出 token 参数约束单次请求。 [Responses 网页搜索](https://developers.openai.com/api/docs/guides/tools-web-search)
3. 代码核对结构化结果中的日期窗口和 URL。证据必须是搜索工具返回过的 Product Hunt 具体产品或发布页。站外链接、榜单及主题页会被拒绝，同一发布的不同链接形式按发布 slug 去重。榜单只能用来发现候选，产品方描述按自述处理。
4. 数据库记录原始响应和用量，再写入校验后的结果及最终状态。公共生成成功后更新公共简报。按需结果保存在自己的请求记录中。

## 用量与预算

`radar usage` 显示累计估算费用和每次请求 JSON。用 `radar usage --day YYYY-MM-DD` 按简报日期或请求窗口的结束日期查询。公共简报和按需请求使用同一份账本。记录总 input、未缓存 input、cache read、cache write（含不同保留时间）、总 output、其中的推理 token、网页动作分类、耗时、状态和估算美元费用。推理 token 已含在 output 中。

估算按 2026-11-22 的公开 Standard 费率计算。模型所报 token 已进入模型计费项，另为已完成的网页工具动作每次保守估算 $0.01。详情以 Platform 账单为准。 [API 定价](https://developers.openai.com/api/docs/pricing) · [缓存计费](https://developers.openai.com/api/docs/guides/prompt-caching)

每次发送前，程序对当前数据库的累计估算费用和待结算金额做检查，并预留 $0.635。返回用量后以估算费用结算。超时等缺少用量的请求保留预留额，避免因未知支出连续重试。SDK 自动重试已关闭。该额度用于本地预估和限制后续请求，托管搜索的最终计费由平台确定。

## 测试

```bash
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked python -m unittest discover -s tests -v
```

离线测试和 GitHub CI 使用模拟 Responses，覆盖站内证据、过期内容、去重、缓存计费、预算拦截、失败恢复和只读网页。

2026-11-22 完成首轮实测。一次请求用时 31.5 秒，生成两条动态。用量为 50,354 input、1,500 output、0 cache read、4,832 cache write，估算总费用 $0.178124。 [AI Context Flow MCP](https://www.producthunt.com/products/ai-context-flow) · [Exa Websets V2](https://www.producthunt.com/products/exa-ai)

同日通过网页实测按需生成，选择 11 月 20 日至 22 日、主题 MCP。返回一条动态，追踪记录包含 7 个搜索词、3 次打开页面，以及 49,015 input、1,460 output、0 cache read、4,888 cache write。单次估算 $0.175074，两轮累计 $0.353198。

## 云端试用

仓库附带容器配置。Web 服务使用 Gunicorn，通过 SQLite 读取简报。启动时提供环境变量 `OPENAI_API_KEY` 即可启用按需生成。网页生成默认使用同一数据库的 $1 累计估算预算。公共生成可以在同一台服务器上用单次命令执行。

```bash
docker compose up -d --build web
docker compose run --rm -e OPENAI_API_KEY web radar run --budget-usd 1.00
```

服务监听宿主机的 `127.0.0.1:8000`。对外试用时可接 HTTPS 反向代理。定时生成可以复用同一条 `radar run` 命令和持久卷，并按实际预算设置累计额度。
