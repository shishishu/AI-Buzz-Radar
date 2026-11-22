# Agent 系统阅读清单 · 2026-11-22

## The components of agent memory

2026-11-06 · Anthropic Engineering · 上下文与记忆

**推荐理由**　帮助你决定哪些跨会话笔记可以直接复用，哪些会影响后续行动、应先回查原始日志再采信。

**1 分钟速览**　文章把记忆分成两步：执行时写下可能有用的笔记，后台再对照会话记录纠错。《宝可梦》案例中，错误的地标笔记让 Claude 三次跌回旧路线；核对记录并改写后，Claude 穿过月见山，抵达下一座城市。这个案例展示了错误如何跨会话延续，但不能据此估算普遍收益；定期复查也有算力成本。

原文依据 · Dreaming can correct memory · “The transcript gave Claude a ground truth to validate its memory against.”

**1 小时深读**

- 15 分钟 · 读《Dreaming can correct memory》并对照图 7，画出从错误地标笔记、误判当前位置到重复走错路的因果链。
- 20 分钟 · 读《Thinking backward, looking forward》，比较即时写入、后台整理和直接检索原始记录，分别标出它们在信息可用性、算力和纠错上的取舍。
- 25 分钟 · 实作：在一个跨会话的文档整理任务中植入一条过时笔记，对比无笔记、直接复用、回查日志后复用三组的完成率与额外耗时。

[阅读原文](https://www.anthropic.com/research/components-of-agent-memory)

## Building strong safety evaluations

2026-11-13 · Anthropic Engineering · 评测与可靠性

**推荐理由**　帮助你决定哪些评测项用程序判分，哪些需要模型裁判，以及更换裁判模型前应做哪些回归检查。

**1 分钟速览**　核心建议是把总分拆成可独立判断的是非项：有明确真值时优先用程序检查，需要理解语境时再用模型裁判。文中用匹配“Yes”却漏掉后续拒绝的例子说明误判机制，并建议交换成对答案的顺序来检查位置偏差。该节给出了诊断方法，没有量化校准后的改进幅度。

原文依据 · Carefully calibrate your grader · “Opt for a set of yes/no questions over a single overall score.”

**1 小时深读**

- 15 分钟 · 读《Keep measures internally valid》关于内部效度的定义，再读《Carefully calibrate your grader》的判分例子，区分你想测的行为和裁判实际识别的信号。
- 20 分钟 · 精读《Carefully calibrate your grader》，把一条笼统的合格标准拆成三条是非题，为每题写一个正例和一个容易误判的边界反例。
- 25 分钟 · 实作：用人工标注的小样本检查裁判，再交换成对答案的顺序重评；逐条记录翻判和分歧，找出需要改写的规则。

[阅读原文](https://www.anthropic.com/research/building-strong-safety-evaluations)

## Testing Claude on real-world electronics design

2026-11-09 · Anthropic Research · 工具与执行

**推荐理由**　帮助你判断面对高重复的工具调用，是继续用现成接口逐步操作，还是投入时间编写专用工具，并把结果交给独立检查。

**1 分钟速览**　KiCad 的现有接口每次只布一条线。面对一个 100 针连接器的长走线，Claude 花约半小时写了网格寻路工具，之后每条长走线约需一秒，还调整了敏感走线周边的间距。这里展示的是布线子任务的执行效率，不是整板已通过验证；三台设备仍是原型，尚未完成电气验证。

原文依据 · Using software and documentation · “a router that could lay each long track in roughly a second.”

**1 小时深读**

- 15 分钟 · 读《Using software and documentation》的布线案例，分开记录逐条指定端点的操作成本、自建工具的开发成本和新增间距约束的修改成本。
- 15 分钟 · 读《Limitations and next steps》，列出原型尚未通过的验证项目，区分布线完成和硬件可交付各自需要的证据。
- 30 分钟 · 实作：用带障碍和保留间距的玩具网格比较手动逐条寻路与批量寻路；把编写时间计入总耗时，并用独立检查器统计违规路径。

[阅读原文](https://www.anthropic.com/research/claude-electronics-design)
