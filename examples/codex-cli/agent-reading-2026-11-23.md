# Agent 系统日报 · 2026-11-23

**智能体评测**　2026-11-23　Hugging Face

## How to build and maintain an agentic evaluation

拉曼光谱案例里，只核对缺陷比会让跳过拟合的程序拿满分。补查拟合结果后，重复运行还揭示了偶尔成功与稳定通过的差距。

**推荐理由**　决定能否把光谱拟合交给智能体无人值守时，评分器能否识别漏做的步骤，以及同一任务能否稳定通过，都会改变上线判断。

### 深读 · 约 15 分钟

#### Summary

**用已知对错的解测试评分器**

作者把评分器也当成测试对象。参考解应当通过，空跑应当失败，故意省略必要工作的方案则用来检验评分器会不会误放。案例里，省略拟合的方案在八道开发任务中都给出了预期缺陷比。作者因此补查实际拟合结果，并建议再试看似合理的错解和其他正确解，分别检查评分器会不会放过错解或误拒正确解。

[定位原文段落 ↗](https://huggingface.co/blog/agentic-evals#step-5-check-the-evaluation)

**八道任务只有一道三次都通过**

在八道改造后的合成光谱开发任务上，作者用同一套智能体配置把每道任务运行三次。八道任务中，七道至少通过一次，只有一道三次都通过。作者指出，有人复核结果时可以容许重试，无人值守更看重每次都过。复跑时通过十次，首次通过十一次，两轮各有二十四次尝试。样本仅覆盖这组开发光谱，推广到新光谱仍需验证。

[定位原文段落 ↗](https://huggingface.co/blog/agentic-evals#step-7-report-the-score)

**一次智能体评测如何留下证据**

| 对照项 | 原文要点 |
| --- | --- |
| 任务与环境 | 任务提供指令，模型和工具在固定环境中运行 |
| 重复尝试 | 评测框架对每道任务发起多次独立运行 |
| 结果评分 | 每次运行结束后，评分器检查环境的最终状态 |
| 证据留存 | 每次运行保留轨迹，与分数一起供复核 |

[图表依据 ↗](https://huggingface.co/blog/agentic-evals#the-anatomy-of-an-agentic-evaluation)

#### Thinking

**安装依赖的能力该计入拟合成绩吗？**

作者在运行轨迹里发现，部分未生成结果的尝试始于缺少数值计算库，任务原本要求智能体自行安装。若实际部署会预装依赖，我会用固定版本做一组对照，保持模型、智能体框架、光谱任务和重复次数一致，按任务记录结果文件缺失、拟合不合格和通过的次数。若仍需在陌生环境自行配置，则应另测安装能力。

[定位原文段落 ↗](https://huggingface.co/blog/agentic-evals#step-6-run-it-and-read-the-traces)

[阅读原文 ↗](https://huggingface.co/blog/agentic-evals)

**研发自动化**　2026-11-18　OpenAI

## Research acceleration: The jagged frontier

OpenAI 的内部数据显示，编码智能体独立完成科研任务的比例随工时和任务类型而变。监控训练的成功率高于编写推理服务代码。

**推荐理由**　给科研工程流程划分自动执行与人工验收的边界时，按任务类型统计的独立成功率会影响哪些步骤适合先委派，哪些步骤仍需逐项验收。

### 深读 · 约 15 分钟

#### Summary

**先审一项，再批量交给智能体**

报告访谈了来自预训练、后训练和安全方向的十名研究人员。他们会把实现、调试和监控实验交给智能体，同时检查分析假设和交付质量。一名研究员把批量编写评测任务改成先让智能体做一项，由自己审阅并修改样例，再让它扩展到其余任务。访谈也记录了无效的分析假设、不可用的数据产物，以及启动实验时走弯路。

[定位原文段落 ↗](https://openai.com/index/research-acceleration-jagged-frontier#changes-in-research-workflows)

**两个工时组的独立完成率都上升**

报告根据预计所需的人工工时给已委派的科研任务分组，比较三月至十月的独立完成率。预计需人工两到四小时的任务，成功率从 23% 升到 46%。预计需四到八小时的任务则从 13% 升到 35%。这些估计值对应各档内无需人工介入便成功的任务占比。按工作内容拆分，监控训练任务的独立成功率估计为 79%，启动训练任务为 35%。

[定位原文段落 ↗](https://openai.com/index/research-acceleration-jagged-frontier#:~:text=estimated%20success%20rose%20from)

**各类委派任务的独立成功率估计（2026 年 8 月 1 日至 10 月 18 日）**

| 对照项 | 原文要点 |
| --- | --- |
| 沟通 | 69% |
| 分析 | 58% |
| 构建 | 43% |

[图表依据 ↗](https://openai.com/index/research-acceleration-jagged-frontier#tasks-delegated-to-models-and-success-rates)

#### Thinking

**成功率上涨有多少来自任务选择？**

作者提醒，同一工时档里的委派任务可能随时间变化，模型进步和研究员改派任务都可能影响观测成功率。要估计模型本身的贡献，我会抽取一批实际委派任务，固定输入、可用工具和验收规则，让各版本独立重跑，再与同期真实委派记录对照。两组结果分别用来衡量固定任务上的能力变化和实际流程中的交付表现。

[定位原文段落 ↗](https://openai.com/index/research-acceleration-jagged-frontier#tasks-delegated-to-models-and-success-rates)

[阅读原文 ↗](https://openai.com/index/research-acceleration-jagged-frontier)

**端侧模型**　2026-11-11　QVAC · Hugging Face

## BotPsy: On-Device Personal Assistant with a Sub-Billion-Parameter Agentic Language Model

八亿参数的 BotPsy 经后训练提升了多轮工具调用能力，在部分流程中得分超过同场的二十亿参数模型，开放式检索仍是短板。

**推荐理由**　为端侧助手选模型时，如果主负载是低到中等难度的工具操作，多轮测试成绩足以让 BotPsy 进入候选。能否满足响应预算则取决于目标设备上的实测延迟。

### 深读 · 约 15 分钟

#### Summary

**先学工具调用，再用蒸馏恢复通用能力**

作者以八亿参数的 Qwen3.5 为底座，先用工具调用对话做监督微调，再让学生模型生成回答，每条提示由对应的专家教师逐词元反馈。三位教师分别专攻工具使用、通用推理和指令遵循。随后两轮强化学习先侧重工具调用，按工具名和参数给部分分，再纳入数学、代码和模拟工作场景等可验证任务。作者观察到，蒸馏补回了微调阶段损失的知识与指令遵循表现。

[定位原文段落 ↗](https://huggingface.co/blog/qvac/botpsy#training-procedure-four-stages-three-types-of-feedback)

**多轮排障得分高，银行任务仍难**

在 BFCL v4 的多轮子项中，BotPsy 得 46.1 分，底座得 7.5 分。在另一项 τ²-bench 测试中，电信场景需要智能体持续与用户对话，并逐步引导用户完成故障排查，它得 82.5 分，同场二十亿参数的对照模型得 69.3 分。各项满分均为一百分。这些测试要求模型在连续交互中维持状态。银行场景来自 τ³-bench 多轮测试，五个受测模型都低于五分。

[定位原文段落 ↗](https://huggingface.co/blog/qvac/botpsy#multi-turn-conversations)

**三项工具与智能体基准得分（各满分 100 分）**

| 对照项 | 原文要点 |
| --- | --- |
| ACEBench | BotPsy 58.7 分，底座 30.1 分，Qwen3.5-2B-Think 55.4 分 |
| Claw-Eval | BotPsy 46.5 分，底座 39.3 分，Qwen3.5-2B-Think 48.9 分 |
| BrowseComp-Plus | BotPsy 4.5 分，底座 1.9 分，Qwen3.5-2B-Think 2.8 分 |

[图表依据 ↗](https://huggingface.co/blog/qvac/botpsy#tool-use--agents)

#### Thinking

**更少的推理词元能换来更低的端侧延迟吗？**

作者只在五个模型都答对的共同题集上比较每道题的推理词元数，而且各用自己的分词器。若要确定端侧响应预算，我会在同一台目标设备上固定推理引擎和量化精度，让候选模型执行同一批实际工具任务，同时记录验收通过率、端到端延迟分布和超时比例，再按相同的延迟预算比较交付表现。

[定位原文段落 ↗](https://huggingface.co/blog/qvac/botpsy#inference-efficiency)

[阅读原文 ↗](https://huggingface.co/blog/qvac/botpsy)
