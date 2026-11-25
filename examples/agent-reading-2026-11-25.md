# Agent 系统日报 · 2026-11-25

*首次入选*　**工具结果交付**　2026-10-30　arXiv

## Fidelity Collapses with Table Size, Not Turn Count: Delivery Architecture in a Deployed Tool-Using Agent

### 核心看点

同样筛选下午起飞的航班，结果表从 5 行增至 100 行，Gemini 2.5 Flash 转述结果的满分率从 83% 降到 6%。改由工具直接交付结果，这组实验的 93 次运行全部答对。

### 内容摘要

作者固定六条航线的查询结果，每次只取表的前若干行。小表就是大表的开头，同一条筛选指令在每个表长、每条航线上各测三次。模型在第一轮筛选就出现了随表长增加而变多的错误。

两条路径的区别在于谁交付记录：一条由模型筛选并重述航班；另一条把记录保存在会话里，由模型给出筛选条件，工具执行后直接返回匹配的行。 [原文章节](https://arxiv.org/html/2611.00442v1#S5.SS1.SSS0.Px1)

![随行数增加，橙色模型转述曲线下降，蓝色直接交付曲线保持在 100%。](figures/originals/677db8c639baf2bab57df4384d153ad562d49688a6e16a373f44c9ad9cb07281.png)

**图 2 · 工具结果表变长时，交付准确率如何变化**　同一份结果按行扩展。六条航线汇总后，Flash 转述组在 100 行时的准确率降至 6%，直接交付组的 93 次运行均正确。阴影为 95% Wilson 区间。 [arXiv 原图出处](https://arxiv.org/html/2611.00442v1#S5.F2)

### 延伸思考

直接交付方案同时改了两件事：跨轮保存记录，以及由工具返回结果。实验测到的是两者合起来的收益。 [原文章节](https://arxiv.org/html/2611.00442v1#Sx1.SS0.SSS0.Px4)

如果你的智能体已经保存了工具结果，可以用同一份记录和筛选条件分别走两条交付路径，逐行核对。这样才能看出，仅换掉最后的转述步骤能挽回多少错误。

[英文原文](https://arxiv.org/html/2611.00442v1)

*再度入选*　**命令执行沙箱**　2026-11-18　OpenAI

## Inside the Codex sandbox

### 核心看点

在 Codex 配置里接入本地 stdio MCP 服务，启动命令默认仍以当前用户的权限运行。OpenAI 用一个记忆服务演示了另一种配置：离线启动，只允许写入 npm 缓存和服务的数据目录。

> 上次入选于 2026-11-21

### 内容摘要

示例先创建记忆服务的数据目录，把固定版本的 npm 包存入缓存。接着用专用权限配置启动服务，让它从缓存加载依赖。

文件与网络限制会由子进程继承。这样即使服务通过 npx 启动，也能在禁网时读到所需的包，并在指定目录保存记忆。 [定位原句](https://openai.com/en-US/index/inside-the-codex-sandbox/#:~:text=without%20network%20access%2C%20with%20writes%20limited%20to%20the%20npm%20cache%20and%20the%20server%E2%80%99s%20data%20directory)

![流程图中，配置和管理员设定的约束共同确定会话权限配置。Codex 据此在 macOS、Linux 或 Windows 的沙箱中启动命令。子进程继承限制，可选的网络代理按域名规则筛选请求。](figures/originals/74f94b4b39f0ed4ee3ac375a02fef9debf378e8fde8f3e36db6d8c15258c4e88.webp)

**Codex 如何把权限配置应用到命令**　Codex 按会话权限配置启动命令，子进程继承沙箱限制。启用网络代理时，由代理执行域名规则。 [OpenAI 原图出处](https://openai.com/en-US/index/inside-the-codex-sandbox/)

### 延伸思考

Codex 无法从启动命令推断服务实际需要哪些文件或网络资源。同样能离线启动的两个服务，执行工具调用时可能需要不同的权限。 [原文章节](https://openai.com/en-US/index/inside-the-codex-sandbox/#example-sandboxing-an-mcp-server)

配置自己的服务时，可以分开验证启动和一次典型调用。若只有调用失败，再核对它需要的目录或域名，比直接给整个服务放宽权限更有针对性。

[英文原文](https://openai.com/en-US/index/inside-the-codex-sandbox/)　[官方中文译文](https://openai.com/zh-Hans-CN/index/inside-the-codex-sandbox/)

*首次入选*　**智能体记忆层**　2026-10-28　LangChain

## Building Evidence-Grounded Agent Memory with OpenWiki and Graphs

### 核心看点

给智能体加一份维基，值不值取决于问题。在合成保险文档上，单段查找用关键词搜索同样准、还更快；遇到需要串联多份文档的问题，维基把准确性得分从 0.10 提到 0.52（满分 1）。

### 内容摘要

作者固定模型、指令和 111 份文档，把问题分成 80 道单段查找题和 50 道跨文档题，每题问三次，分别看答案得分和引用段落的重合度。

维基能帮智能体串起分散的条款，但同一道题可能引出不同依据。作者把维基中的陈述连到原文段落；在跨文档题上，得分从 0.52 升至 0.66，三次回答的引用重合度翻倍。 [定位原句](https://www.langchain.com/blog/building-agent-memory-openwiki-graphs#:~:text=Accuracy%20rose%2027%25%2C%20citation%20consistency%20doubled)

![原文四幅柱状图比较仅搜索、只用 wiki 及 wiki 加证据图的正确率、引用一致性、每个正确回答的成本和中位回答时间。](figures/originals/89f2c95cd73d5cdcf8e73fc98cc2ec6685f15155c795b866a54a4489cd86ec0c.png)

**三种记忆方案怎样回答跨文档查询**　作者比较了三种方案。从单用 wiki 到加入证据图，正确率从 0.52 升到 0.66，中位回答时间从 30 秒降到 18 秒。 [LangChain 原图出处](https://www.langchain.com/blog/building-agent-memory-openwiki-graphs#:~:text=Better%20accuracy%2C%20lower%20cost%2C%20faster%20answers)

### 延伸思考

文中的每题成本只算检索与作答。最初编译 111 份文档另花了 4.15 美元，后来每新增一份约花 0.09 美元。 [定位原句](https://www.langchain.com/blog/building-agent-memory-openwiki-graphs#:~:text=The%20analysis%20below%20excludes%20compilation%20and%20update%20costs)

如果知识库更新频繁，可以按真实比例回放查找题和跨文档题，再把维护费用摊到每道答对的题上。这才是决定要不要长期维护维基的成本。

[英文原文](https://www.langchain.com/blog/building-agent-memory-openwiki-graphs)
