# Agent 系统日报 · 2026-11-21

## 让同一个模型在编码框架里少走几步

编码代理训练 · Hugging Face · 原发于 2026-11-20

在 Pi 编码框架里训练适配器后，同一基础模型在 51 道高难题上的一次通过率从 39.2% 升至 64.7%。换到业务自动化任务，收益落入测量噪声。

**推荐理由**　团队的工具调用成本已经很高时，这篇文章能帮你估算，为固定编码框架训练适配器究竟值不值。

### 15 分钟深读 · 含原文选段

#### 3 分钟 · 让模型在实际使用的框架里训练

通用模型追求跨场景表现，却未必懂得怎样在你选的代理框架里高效使用工具。作者冻结 Qwen3.8-27B 的基础权重，为三个框架分别训练轻量适配器。训练不另写代理循环，而是让原版框架在沙箱里执行编码任务，由代理服务器记录模型实际生成的词元。奖励以测试判定的正确性为主，再给更高效的工具使用一点额外奖励。

[定位原文段落 ↗](https://huggingface.co/blog/harness-adapters-at-scale#training-inside-agent-harnesses)

**一次框架内训练的反馈路径**

1. 原版编码框架执行任务
2. 记录模型输出与工具动作
3. 测试用例判定完成情况
4. 更新框架专用适配器

#### 7 分钟 · 同一个 Pi，最难的题多做对了多少

作者关闭思考模式，让基础版和适配版各做一遍 SWE-bench Pro 最难的 51 题。在 Pi 中，专用适配器把一次通过率从 39.2% 提到 64.7%，新解出 15 题，也丢了原本能解的 2 题。在这套题上，三个框架分别只看两版都解出的题，专用版每题工具调用少 56%–72%；这不是全部任务的总成本降幅。

[定位原文段落 ↗](https://huggingface.co/blog/harness-adapters-at-scale#final-evaluation-results)

**合并权重怎么选：第 120 步适配器的对照（Terminal-Bench 2.1，每框架 89 题，三框架均值）**

| 对照项 | 原文要点 |
| --- | --- |
| 基础模型 | 一次通过率 43.3%；每题 49.2 次工具调用 |
| 每份更新取 ⅓ | 一次通过率 49.2%；每题 35.6 次工具调用 |
| 每份更新取 ½ | 一次通过率 52.5%；每题 25.9 次工具调用 |
| 每份更新全量相加 | 一次通过率 50.0%；每题 13.4 次工具调用 |

[图表依据 ↗](https://huggingface.co/blog/harness-adapters-at-scale#super-adapter-merging-all-adapters-into-one)

#### 5 分钟 · 换任务也换框架，就重新测

作者改用 AutomationBench 自带的代理循环，测试了 300 道业务自动化任务。以全部断言通过为准，合并版的一次通过率为 23.7%，基础版为 23.0%，没有显示出明确的迁移收益。选型时，建议先用未参与训练的自家任务，在同一框架内比较通过率和每题开销；如果任务类型和代理循环都要换，就别把编码基准上的收益算进预算。

[定位原文段落 ↗](https://huggingface.co/blog/harness-adapters-at-scale#evaluation-on-out-of-distribution-tasks-and-setup)

[阅读原文 · Introducing harness adapters: adapt your favorite model to your harness to improve performance and cost ↗](https://huggingface.co/blog/harness-adapters-at-scale)

## Codex 的沙箱边界画在哪里

进程隔离 · OpenAI · 原发于 2026-11-18

Codex 默认允许修改工作区并阻止联网，却仍可能读到仓库外的敏感文件。接入外部工具时，还要确认它的启动命令是否也受沙箱约束。

**推荐理由**　如果你的代理能运行 shell、访问密钥或接入 MCP 服务，这篇文章能帮你判断，哪些权限需要分别配置。

### 15 分钟深读 · 含原文选段

#### 3 分钟 · 工作区可写，不等于只能读工作区

Codex 在宿主系统上运行命令，子进程继承同样的限制。以 Git 仓库为工作区时，默认配置允许修改源码，但将 Git 元数据目录和 Codex 配置目录设为只读，并关闭网络。构建工具仍能在系统权限范围内读取仓库外的依赖，命令也因此可能读到敏感文件。若任务不该接触密钥，建议对存放密钥的路径明确设为拒绝访问。

[定位原文段落 ↗](https://openai.com/index/inside-the-codex-sandbox#choosing-the-sandbox-boundaries)

#### 7 分钟 · 给 MCP 服务单独套一层沙箱

Codex 不会自动把通过标准输入输出通信的 MCP 服务放进沙箱，因为它无法可靠推断服务需要访问哪些文件和网络资源。文章以记忆服务为例：作者先建好数据目录并缓存固定版本的依赖，再用单独的权限配置离线启动，把写入范围限定在包缓存和服务数据目录。接入类似服务时，建议单独核对它的读写路径和联网需求。

[定位原文段落 ↗](https://openai.com/index/inside-the-codex-sandbox#:~:text=with%20writes%20limited%20to%20the%20npm%20cache)

**单条命令的权限请求：执行框架按用户设置裁决**

| 对照项 | 原文要点 |
| --- | --- |
| 沿用默认 | 使用当前轮次的沙箱配置 |
| 申请额外权限 | 获准后扩大访问范围，但仍在沙箱内运行 |
| 申请沙箱外执行 | 获准后在沙箱外运行，不只是放宽某条规则 |

[图表依据 ↗](https://openai.com/index/inside-the-codex-sandbox#:~:text=When%20use_default%20is%20specified%2C%20the%20harness%20uses%20the)

#### 5 分钟 · 同一套启动接口，不同的系统边界

Codex 在三个平台上共用一套启动接口，但由各自的系统机制执行限制：macOS 用 Seatbelt，Linux 结合 bubblewrap 和系统调用过滤，Windows 正在兼容设备上转向 MXC。文章指出，Windows 在代理模式下会阻止直接连接外部主机，但宿主机的回环服务仍可访问。如果也要隔离本机开发服务，建议在目标系统上验证，别只检查外网是否被挡住。

[定位原文段落 ↗](https://openai.com/index/inside-the-codex-sandbox#network-access)

[阅读原文 · Inside the Codex sandbox ↗](https://openai.com/index/inside-the-codex-sandbox)

## 网站认出了代理，怎样知道它在替谁办事？

网站身份与访问控制 · Cloudflare · 原发于 2026-11-05

云端代理替多人访问网站，认出代理不等于知道它代表谁。网站可以按操作风险索取必要信息，在能区分账号时只限制涉事账号，而不是封掉整个代理。

**推荐理由**　适合正在做账号风控的工程师。按代理封禁可能影响它服务的所有人，原文拆开了账号归属、请求签名和用户授权。

### 15 分钟深读 · 含原文选段

#### 3 分钟 · 为什么封代理会误伤用户

文章用一名替四位客户跑腿的助理说明共享代理的难题：一位客户让她买手机，事后却否认授权。商家只见过助理，很难证明是谁下的单。银行也面临类似困境：当其中一人的行为触发风控，封掉助理会连带挡住另外三人。对网站来说，认出代理只是第一步；处理争议还得分清它这次代表谁，以及谁应为这次操作负责。

[定位原文段落 ↗](https://blog.cloudflare.com/trusted-agent-delegation/#:~:text=the%20only%20person%20it%20can%20ban)

#### 7 分钟 · 代理签名能证明什么

Cloudflare 建议把代理身份和用户身份分开。Web Bot Auth 让代理签署请求，网站据此识别代理及其运营方，却不能只凭签名知道代理在替谁办事。用户侧只需按操作风险披露必要信息：有时网站只需要判断请求是否可信，不必知道用户是谁。如果一次访问经过多个代理或云浏览器，如何让网站识别整条中介链，仍有待定义。

[定位原文段落 ↗](https://blog.cloudflare.com/trusted-agent-delegation/#:~:text=allows%20an%20Agent%20to%20sign%20its%20requests)

**用户身份披露四档：网站能把哪些请求关联起来**

| 对照项 | 原文要点 |
| --- | --- |
| 无标识 | 不提供用户标识 |
| 会话级 | 只关联同一会话内的请求，可累积会话信誉 |
| 账号级 | 跨会话识别同一账号，可绑定网站账号与代理账号 |
| 个人级 | 跨运营方识别同一人，可用于高风险操作 |

[图表依据 ↗](https://blog.cloudflare.com/trusted-agent-delegation/#:~:text=When%20discussing%20Agent%20Identity%2C%20Web%20Bot%20Auth%20%28WBA%29)

#### 5 分钟 · 先把处置范围缩到账号

据 Cloudflare 介绍，客户已能按代理查看流量并设置访问规则。开通账号滥用防护早期访问的站点，还能在登录和注册时识别代理；某个账号被滥用时，可以用防火墙规则按用户哈希标识处置，不必封掉整个代理。落地时可先用这些信号缩小封禁范围；如果用户对付款提出争议，仍需另行确认授权，不能把识别出账号当成授权凭证。

[定位原文段落 ↗](https://blog.cloudflare.com/trusted-agent-delegation/#:~:text=a%20WAF%20rule%20on%20its%20Hashed%20User%20ID)

[阅读原文 · Agents aren’t humans \(but they kinda are\) ↗](https://blog.cloudflare.com/trusted-agent-delegation/)
