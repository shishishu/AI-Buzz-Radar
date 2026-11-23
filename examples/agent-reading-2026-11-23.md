# Agent 系统日报 · 2026-11-23

## 三次里成功一次，离无人值守还有多远？

智能体评测 · Hugging Face · 原发于 2026-11-23

八道任务，每题跑三次。允许重试，模型能做对七道；要求三次全对，只剩一道。上线前选哪一个指标，取决于失败后有没有人接手。

**推荐理由**　同一模型在同一批任务上的两种通过率，足以改变你对重试次数、人工复核和上线门槛的选择。

### 15 分钟深读 · 含原文选段

#### 3 分钟 · 评测看最终产物，不听口头报完

智能体评测不只核对回答，还检查智能体在环境中留下的最终状态。任务给出指令，智能体运行框架把模型接到工具上，让它在固定版本的环境里操作；评测框架负责重复运行，验证器在每次尝试结束后判分。分数只能告诉你过没过。遇到低分，建议先对照运行轨迹和最终产物，再判断该改模型、运行环境还是评分规则。

[定位原文段落 ↗](https://huggingface.co/blog/agentic-evals#the-anatomy-of-an-agentic-evaluation)

#### 7 分钟 · 先查评分漏洞，再区分成功与稳定

作者用拉曼光谱拟合做评测，发现如果只检查 D/G 峰强比，不做拟合也能过关，于是补上对拟合结果的检查。改编后的八道任务各跑三次，gpt-oss-120b 在 7/8 道任务上至少成功一次，却只在 1/8 道任务上三次都成功。有人工复核时，可以参考前者；无人值守更应关注后者。不过，这八道开发任务不足以推断模型在新光谱上的表现。

[定位原文段落 ↗](https://huggingface.co/blog/agentic-evals#results)

**24 次拉曼拟合尝试：首条回复是否标记完成**

| 对照项 | 原文要点 |
| --- | --- |
| 首条回复就标记完成（19 次） | 7/19 次通过；11/19 次未生成结果文件；1/19 次未通过拟合检查 |
| 首条回复未标记完成（5 次） | 4/5 次通过；1/5 次未通过拟合检查 |

[图表依据 ↗](https://huggingface.co/blog/agentic-evals#step-6-run-it-and-read-the-traces)

#### 5 分钟 · 公开可审查的部分，保护在用试题

不公开正式测试题，可以减少题目进入训练数据的风险，却也让外部人员无法逐题核查。作者建议按组件决定开放范围：发布任务设计方法、开发样例和评分方法，把仍在使用的测试题和答案分开保护。如果你在维护团队基准，可以先开放这些可复用材料，再为不宜公开的题目安排受控审查；保密不能代替验证。

[定位原文段落 ↗](https://huggingface.co/blog/agentic-evals#4-open-sourcing-an-evaluation-strategically)

[阅读原文 · How to build and maintain an agentic evaluation ↗](https://huggingface.co/blog/agentic-evals)

## 哪些研发任务适合让代理独立完成？

研发自动化 · OpenAI · 原发于 2026-11-18

OpenAI 的内部估计显示，代理独立完成训练监控任务的比例为 79%，编写推理与服务栈代码为 25%。两者分母都是研究员实际委派的任务。

**推荐理由**　如果正在挑选第一批委派任务，按工作类型拆开成功率，比按预计工时设一道统一门槛更有参考价值。

### 15 分钟深读 · 含原文选段

#### 3 分钟 · 近半数，指的是哪批任务

OpenAI 按人类完成任务所需的预计工时，对交给代理的研发任务分组。2026 年 3 月至 10 月，两到四小时组的估计成功率从 23% 升到 46%，四到八小时组从 13% 升到 35%。成功指代理无需人工介入就完成任务，分母是各组已委派的任务。这不是全部研发工作的自动化比例，也不能直接换算成团队节省的工时。

[定位原文段落 ↗](https://openai.com/index/research-acceleration-jagged-frontier#:~:text=tasks%20estimated%20to%20require%20two%20to%20four%20hours)

#### 7 分钟 · 监控训练和写服务栈不能一起算

在同一观察窗口内，监控训练运行是否出问题的任务，估计有 79% 能由代理独立完成；编写推理与服务栈代码的任务只有 25%。两个比例各以相应类型的委派任务为分母。原文还提醒，即使预计工时相同，研究员挑来委派的任务也可能随时间变化，所以成功率上升不能全归功于模型变强。

[定位原文段落 ↗](https://openai.com/index/research-acceleration-jagged-frontier#tasks-delegated-to-models-and-success-rates)

**各类委派任务的无人工介入成功率（2026 年 8 月 1 日至 10 月 18 日，估计）**

| 对照项 | 原文要点 |
| --- | --- |
| 沟通类 | 69% |
| 分析类 | 58% |
| 构建类 | 43% |

[图表依据 ↗](https://openai.com/index/research-acceleration-jagged-frontier#tasks-delegated-to-models-and-success-rates)

#### 5 分钟 · 能帮忙实现，不等于能独立选题

两次模型发布中，后训练和安全监控受访者列举的关键想法都由人提出，模型协助实现。但在 GPT-6.2 Astra 的预训练中，有研究者说，自己提出的想法在采纳 Codex 建议的改动后才开始奏效。这些回顾来自少数关键贡献者，不能证明代理能独立选题。用于团队分工，可以让代理参与推敲和实现，仍由人决定哪些假设值得验证。

[定位原文段落 ↗](https://openai.com/index/research-acceleration-jagged-frontier#where-big-ideas-come-from)

[阅读原文 · Research acceleration: The jagged frontier ↗](https://openai.com/index/research-acceleration-jagged-frontier)

## 8 亿参数的助手，适合把哪些工具搬到端侧？

端侧智能体 · QVAC · Hugging Face · 原发于 2026-11-11

在作者的复杂工具任务中，BotPsy 从同尺寸基座的 17.9 分提高到 39.5 分（满分 100）。拆开任务看，多步检索仍是明显短板。

**推荐理由**　如果想把云端调用移到手机，这组分项实验能帮你从低风险的单次操作入手，再决定哪些多步流程值得迁移。

### 15 分钟深读 · 含原文选段

#### 3 分钟 · 小模型怎么学会用工具

查日历之类的操作不一定要交给云端大模型，难点是让小模型选对工具、填对参数，还知道何时不该调用。作者从 Qwen3.5-0.8B 出发，先用工具调用示例做监督微调，再让擅长工具使用、推理和指令遵循的三个教师模型提供逐词元反馈，补回微调后下滑的通用能力。两轮强化学习先用规则给工具名和参数打分，再加入更多可验证任务和多步工具操作。

[定位原文段落 ↗](https://huggingface.co/blog/qvac/botpsy#training-procedure-four-stages-three-types-of-feedback)

#### 7 分钟 · 多步任务进步明显，但仍落后于单次调用

作者把多轮对话或涉及多个工具的场景归为复杂任务。按场景汇总，BotPsy 得 39.5 分（满分 100），高于同尺寸基座的 17.9 分和 20 亿参数对照模型的 30.8 分。设备与系统管理这组复杂任务尤其直观：它从基座的 15 分提高到 46 分。这些分数不是实际设备上的任务成功率；在作者的测试中，多步任务得分仍低于单次调用。

[定位原文段落 ↗](https://huggingface.co/blog/qvac/botpsy#the-largest-gains-are-in-multi-step-tasks)

**工具基准得分（满分 100；依次为 BotPsy、同尺寸基座、Qwen3.5-2B-Think）**

| 对照项 | 原文要点 |
| --- | --- |
| 函数调用（BFCL v4） | 44.0／23.4／37.7 |
| 工具交互（ToolSandbox） | 64.6／30.5／41.2 |
| 智能体评测（Claw-Eval） | 46.5／39.3／48.9 |

[图表依据 ↗](https://huggingface.co/blog/qvac/botpsy#tool-use--agents)

#### 5 分钟 · 从低风险的只读操作试起

作者推荐用英语处理低到中等难度的任务；印地语和俄语的指令遵循得分明显偏低。模型也不适合高风险自动决策，或涉及资金、个人信息和健康的敏感应用。工程上，建议先试点不涉及敏感数据的只读设备状态查询，只开放完成任务所需的工具。如果原型需要写入，先向用户展示将执行的操作，再请求确认。端侧运行不是放宽权限的理由。

[定位原文段落 ↗](https://huggingface.co/blog/qvac/botpsy#intended-use-and-limitations)

[阅读原文 · BotPsy: On-Device Personal Assistant with a Sub-Billion-Parameter Agentic Language Model ↗](https://huggingface.co/blog/qvac/botpsy)
