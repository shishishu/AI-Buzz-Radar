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

浏览 [本地简报](http://127.0.0.1:8000/)。默认查找最近三个 Product Hunt 发布日期，`run --day YYYY-MM-DD --days 3` 可以回查。已生成的日期会复用原简报，`--force` 会重新研究并在成功后更新。简报和请求记录保存在 `data/product-hunt.sqlite3`，可以用全局参数 `radar --db PATH` 指定文件。

## Agent 如何工作

1. 从 SQLite 读取最近 14 天简报以去重，把最多 25 条历史路径交给模型作为检索提示。
2. 模型通过 Responses API 的 `web_search` 查阅 Product Hunt 的榜单、主题和具体发布页。启动配置限定 `producthunt.com`，并用低搜索上下文、6 次工具调用参数和 6,500 个输出 token 参数约束单次请求。
3. 代码核对结构化结果中的日期窗口和 URL。证据必须是搜索工具返回过的 Product Hunt 具体产品或发布页。站外链接、榜单及主题页会被拒绝，同一发布的不同链接形式按发布 slug 去重。榜单只能用来发现候选，产品方描述按自述处理。
4. 通过校验的简报和对应请求状态在同一个 SQLite 事务中写入。CLI 和网页从数据库读取。API 失败或结果无法验证时保留已有简报。

## 用量与预算

`radar usage` 显示累计估算费用和每次请求 JSON。用 `radar usage --day YYYY-MM-DD` 查看当日请求。记录总 input、未缓存 input、cache read、cache write（含不同保留时间）、总 output、其中的推理 token、网页动作分类、耗时、状态和估算美元费用。推理 token 已含在 output 中。

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

## 云端试用

仓库附带容器配置。Web 服务使用 Gunicorn，通过 SQLite 读取简报。生成可以在同一台服务器上用单次命令执行。

```bash
docker compose up -d --build web
docker compose run --rm -e OPENAI_API_KEY web radar run --budget-usd 1.00
```

服务监听宿主机的 `127.0.0.1:8000`。对外试用时可接 HTTPS 反向代理。定时生成可以复用同一条 `radar run` 命令和持久卷，并按实际预算设置累计额度。
