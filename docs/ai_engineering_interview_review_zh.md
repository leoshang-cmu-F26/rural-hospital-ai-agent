# Rural Hospital AI Agent：AI Engineering Intern 面试复习手册

版本：2026-10-28。根据当前仓库实现整理；数据库覆盖及测试数量是本次开发阶段的验证记录，不代表线上始终使用同一版本。

使用方式：先练习第1节的项目介绍，再学习第2–10节的技术细节，最后用第11–14节模拟追问。英文回答是可改写的示例，不需要逐字背诵。谈论个人贡献时，仅保留你能解释、确认并承担的工作，团队贡献应如实区分。

## 1. 用一分钟解释这个项目

### 1.1 项目解决什么问题？

用户可以用自然语言调查医院的财务历史和医疗可及性。系统关联 CMS 医院目录和成本报告、Census 县级统计、HRSA 短缺地区与医疗人员证据，调用确定性计算工具，再生成带来源和限制的回答。

核心不是让模型凭知识猜测医院情况，而是让它协调受约束的数据工具。原型提供财务指标、趋势、医院比较、区域分析、图表，以及解释方法定义的文档 RAG。

**英文一分钟版本：**

> I built a rural hospital investigation agent that combines structured public data with natural-language interaction. Users can identify a hospital by name and location, investigate financial trends, and examine county-level healthcare-access context. The model selects tools and explains findings, while Python services retrieve versioned data and calculate the indicators. I moved recurring source retrieval into explicit import jobs backed by Supabase PostgreSQL, added data-quality checks and bounded conversation context, and implemented methodology RAG using OpenAI embeddings and pgvector. The main engineering focus is making incomplete and inconsistent data visible rather than letting the model produce an overly confident conclusion. It is a research prototype, and I have not established real-world decision impact or a comprehensive model-accuracy benchmark.

### 1.2 三个最值得突出、也最需要能解释的设计

1. **模型与计算分离**：LLM 负责工具选择和解释，财务计算与数据质量检查由 Python 执行。
2. **导入与查询分离**：用户请求读取已完成的数据库快照；导入失败不替换上一个可用版本。
3. **证据与解释限制一起返回**：同一个结果中保留来源、年份、缺失原因、财年、被屏蔽指标和覆盖范围。

### 1.3 不能夸大的成果

- 不是预测医院倒闭的模型，也没有训练专门的财务风险分类器。
- 尚未建立真实 public-health 用户的对照任务研究，不能宣称已证明提升决策质量。
- 不保证覆盖所有美国医院；当前实际导入的是 CA、WI、WY。
- 使用 LangChain 的 `create_agent` 和 LangGraph runtime；没有手工构建完整的多主题 StateGraph。
- 当前方法 RAG 使用 pgvector，但没有部署 HNSW、IVFFlat 或 reranker。
- 图表比较可以有2–5家医院；完整调查比较和持久于浏览器的比较身份仍主要支持两家。
- 本地实现与已部署演示可能不同；改动需要部署后才能出现在云端。

## 2. 整体架构与一次请求的完整路径

### 2.1 各层负责什么？

- **前端**：原生 HTML/CSS/JavaScript，负责聊天、有限 Markdown、进度、来源、警告和 SVG 图表。
- **HTTP 层**：FastAPI，Pydantic 校验消息与有限的对话上下文。
- **Agent 层**：LangChain `create_agent`，底层使用 LangGraph runtime；模型通过 `ChatOpenAI` 接入。
- **工具层**：`@tool` 暴露受约束的医院查询、财务、趋势、区域分析、图表和文档检索函数。
- **服务层**：身份解析、数据库查询、计算编排、数据质量和来源元数据。
- **存储层**：Supabase PostgreSQL 保存结构化快照与 pgvector；本地 SQLite 保留坐标缓存和部分可重建索引。
- **离线导入层**：显式运行的 Python CLI 脚本，负责下载、校验、版本记录和完整快照发布。

### 2.2 示例：用户询问 Mile Bluff 财务趋势

1. 浏览器发送用户问题、最近最多6条消息及当前医院身份。
2. FastAPI 校验请求，流式接口先返回一个公开进度事件。
3. 后台工作线程调用共享 Agent 入口；每次调用独立传入上下文。
4. 如果身份不明确，模型先调用医院解析工具；名称相似时不能随意挑选。
5. 模型调用财务趋势工具；工具读取导入年份和各年报告。
6. Python 选择报告、计算指标、检查缺失和财年可比性。
7. 工具结果作为证据交回模型；回调独立发出来源、警告及上下文事件。
8. 模型生成最终解释；浏览器渲染回答。图表请求另附结构化绘图数据。

这是典型的工具调用循环：模型提出工具调用 → 程序执行 → 工具结果进入模型上下文 → 模型继续或结束。LLM 并不直接执行任意 SQL，也不决定计算公式。

**英文追问：Why use an agent instead of a fixed pipeline?**

> The user's intent can vary between identity lookup, financial trends, area-level access, and methodology questions. Tool calling gives us a flexible interface over those operations. I still use deterministic service pipelines inside the tools, because report selection, ratio calculations, and validation should be explicit and testable. For common requests, a compact tool also avoids many model-driven round trips.

**进一步追问：既然很多步骤是固定的，是否每次都需要 Agent？**

不一定。明确的 HTTP 查询和固定图表可以直接调用服务。Agent 的价值主要在自然语言理解、身份澄清和跨工具编排。未来可以把常见确定意图直接路由到轻量服务，减少模型调用；目前不能声称所有意图都已有确定性分类器。

## 3. LangChain、LangGraph、状态与工具调用

### 3.1 当前到底用了哪一部分 LangGraph？

当前调用 `langchain.agents.create_agent(model, tools, system_prompt)`，这个 Agent 运行在 LangGraph runtime 上。它提供工具调用循环和消息执行机制。项目没有另外手写“财务节点 → 可及性节点 → 文档节点”的显式 StateGraph，也没有配置持久化 checkpointer。

**可直接练习的英文回答：**

> I use LangChain's create_agent, which runs on LangGraph. I did not build a custom StateGraph for every topic. My application-level conversation state is explicit but lightweight: bounded recent messages plus a current facility or a two-hospital comparison context. A custom graph would be useful if we needed mandatory review stages, durable workflows, or resumable human approval.

### 3.2 Tool schema 与 prompt 分别有什么作用？

- 工具签名和类型定义可调用的参数结构。
- 工具描述帮助模型判断何时调用。
- SYSTEM_PROMPT 规定来源使用、路由、年份和解释限制。
- 后端仍然必须检查取值范围、身份、缺失和结果可比性。

Prompt 中说“不要比较财年不一致的指标”不能代替代码检查；模型可能选择错误工具，也可能违反解释要求。关键约束应落到服务层，警告还要独立进入前端。

### 3.3 对话记忆如何实现？

浏览器保存：

- 最近最多6条消息，约3轮；每条最多2000字符。
- 当前单家医院的精简身份，例如名称、CCN、州。
- 或两家比较医院的精简身份。

后端将这些内容作为对话数据传入，不把历史消息提升成系统指令。最新明确指定的医院优先于旧上下文。失败或模糊的身份解析可以清除旧目标，避免把“its”错误地套在上一家医院上。

完整报告、图表所有点和检索片段不会作为浏览器历史无限累加。刷新或清空聊天会重置状态；这不是跨设备、跨会话的持久记忆。

### 3.4 Token 增长怎样控制？

限制历史长度、保存精简身份、返回紧凑工具结果、限制名单数量和 RAG top-k。注意，2000字符不是2000 tokens；这只是请求大小的近似约束。

工具结果会进入当前模型调用，所以不能说“工具查询完全不消耗 tokens”。缓存数据库查询不会自动减少模型输入；减少返回字段和工具调用轮次才直接影响模型上下文。

### 3.5 多家图表之后的状态有什么限制？

单家图表更新当前医院，两家图表更新比较对；3–5家图表清除旧的单家/两家横幅，避免把最后解析的一家错误设为唯一目标。更大组的名字保留在有限的最近对话里，没有独立的持久多院记忆。

## 4. 数据工程：为什么先导入数据库？

### 4.1 原来的瓶颈

每次实时访问官网，用户等待时间容易受 CMS/Census/HRSA 的响应、分页、超时和坐标匹配影响。多年份、多医院请求会放大这些问题。

现在把下载与验证放入独立导入任务，查询读取已完成快照。收益是减少官网依赖、提高可重复性，并能解释“分析使用的是哪一版数据”。代价是需要管理刷新、覆盖、历史版本和数据库运维。

### 4.2 当前覆盖的可核实事实

本轮导入检查记录：

- CA、WI、WY，2020–2024年，共2,959条财务源报告记录；一家医院一年可能有多份报告。
- 医院目录共548家：CA 377、WI 140、WY 31。
- 县级统计153个县：CA 58、WI 72、WY 23。
- 三州均有 HPSA 和坐标快照；坐标并非全覆盖，65家明确不可用。
- ACS 包含人口、年龄、保险、贫困和收入等11项估计及对应 MOE。
- AHRF 包含5类医疗人员指标；人数和人口分母保留各自匹配的年份。

这些数量是导入快照，不是实时全国注册表。医院目录与成本报告来源范围不同，不能要求两者记录数量相等。

### 4.3 为什么选 PostgreSQL + JSONB？

PostgreSQL 提供事务、索引、约束、并发读取和 pgvector，减少多个独立服务的运维。JSONB 保留 CMS/AHRF 原始字段，便于追溯和适应字段变化；常用查询键如 CCN、州、年度和 run_id 单独存储或建立索引。

取舍：JSONB 灵活但缺少完全关系化字段的类型约束，深层字段查询也可能较重。后续可以把高频指标、分类和距离物化为专门表，同时保留原始 JSONB。

### 4.4 数据表如何支持版本？

财务：`financial_import_runs` 记录导入和来源，`financial_report_rows` 保存报告，`financial_coverage` 指向州/年度的有效版本。

参考数据：`reference_import_runs`、`reference_records`、`reference_coverage`，按数据类型和州管理有效版本。

向量：`methodology_corpora`、`methodology_passages`、`methodology_active`，保存 embedding 配置、来源片段和当前方法文档版本。

### 4.5 为什么需要 active pointer？

新数据写完并验证成功后，才在同一事务中切换有效指针。失败时仍读取旧的完整快照，用户不会看到“正在导入一半”的数据。

事务原子性是 PostgreSQL 提供的保证；不是宣称整个互联网下载也属于同一个数据库事务。远程下载和 embedding 在发布之前进行。

**英文回答：How do you avoid partial imports?**

> I keep imported versions separate from the active coverage pointer. After validating a complete dataset, I publish its rows and update the pointer transactionally. Reads only use the active complete version. A failed refresh leaves the previous snapshot available. Composite foreign keys also prevent a coverage pointer from referencing the wrong state or year.

### 4.6 幂等、更新和完整性

- 通过来源 dataset ID、下载 URL、修改标记和文件哈希记录版本。
- 完整分页、行结构、州和 CCN 校验降低截断风险。
- 来源元数据未变化时可以跳过下载；强制刷新用于检查元数据未变但内容可能改变的情况。
- 失败尝试不覆盖有效数据；财务导入可以按州/年度重新执行。
- 这不是连续 CDC，也不是任意下载断点续传，更不是已配置的自动定时刷新。
- SHA256 证明本地内容与所记录版本一致，不能单独证明来源结论正确。

### 4.7 缺失至少要分三类

1. 数据源完整覆盖，但没有匹配报告。
2. 该州/年度尚未导入，无法判断。
3. 数据库或外部来源访问失败，暂时无法获取。

不能把后两种包装成“医院没有报表”。底层还保存全国源文件的紧凑 CCN inventory，避免把未导入州误判成全国不存在。

### 4.8 为什么用连接池和只读事务？

复用 TLS 连接，避免每个年度查询都重新建立连接。当前读取池最多4个连接；每次读取设置只读事务和15秒 statement timeout。历史年份请求最多4个并发任务，防止无界并发。

注意：只读事务不等于已采用最小权限数据库角色。当前连接配置仍有改为专用只读应用账号的空间。

## 5. 缓存：TTLCache、SQLite 与数据库快照

### 5.1 三者不是同一种东西

- **TTLCache**：进程内短期缓存，速度快，进程重启丢失，多 worker 之间不共享。
- **SQLite 坐标缓存**：本地文件持久化，重启后文件仍在才可复用，不具备云端持久磁盘的自动保证。
- **Supabase 快照**：由导入任务显式更新的共享数据版本，是配置下的分析数据来源，不仅是随时丢弃的内存缓存。

Live geocoding 路径是内存 → SQLite → Census Geocoder。配置参考数据 `database_only` 后，医院坐标走已导入快照；被标记不可用或地址不匹配时不会偷偷回退到旧坐标。

### 5.2 复习几个当前参数

- 参考州快照：TTL 300秒，最多64项。
- 查询 embedding：TTL 1小时，最多256个查询。
- 医院坐标内存缓存：TTL 7天，最多5000项。
- 财务源行缓存：TTL 1小时，最多2000项；实际命中位置取决于读取模式，不能笼统说所有数据库读取都命中它。

这些是工程配置，不是数学最优值。面试中应能说明：TTL 在新鲜度、来源稳定性、数据获取成本和内存之间取舍。

### 5.3 高频追问

**Cache invalidation 怎么做？** 内存短 TTL、导入发布时清理当前进程对应缓存、坐标重用前核对地址、向量使用模型和输入哈希以及 corpus fingerprint。另一个 worker 的缓存仍可能在 TTL 内保留旧版本；目前没有 Redis 广播失效。

**Cache stampede 怎么办？** 当前部分缓存操作加锁保证读写安全，但不等于所有同键请求都实现了 single-flight。高并发下可增加每键请求合并或分布式锁。

**为什么还没用 Redis？** 当前原型规模小，已有持久数据库和本地缓存。多实例部署、共享限流或跨实例缓存失效时，Redis 才更有明确价值。

## 6. 向量 RAG：重点深挖区

### 6.1 数据库查询和 RAG 的边界

“Mile Bluff 2024年的 operating margin 是多少？”使用结构化数据库与计算工具。

“Operating margin 的定义是什么？”使用方法文档检索。

“画趋势图并解释指标定义”可以同时调用两条路径。当前没有把全部医院表当成文本向量化，也没有对每行财务数据做 semantic search。

### 6.2 Ingestion 流程

1. 官方文档经整理后存入 `corpus.json`，带 URL、标题、时间、哈希和可选 PDF 页码。
2. 正文按900字符分块，相邻重叠100字符。是字符，不是 tokens。
3. 对“标题 + topic + 原文片段”生成 embedding。
4. 默认使用 `text-embedding-3-small`，1536维；文档与查询使用同一配置。
5. 把16个现有片段的向量和出处写入 Supabase pgvector。
6. 全部成功后原子切换当前 corpus。重复导入复用相同输入/模型的向量。

900/100 是初始工程选择，没有通过正式实验宣称最优。重叠降低边界丢失风险，但也会产生相似或重复片段。标题与 topic 可以补充上下文，也会影响排序，需要评估。

### 6.3 Query 流程

1. Agent 对方法或不确定性问题调用 `search_methodology_documents`。
2. 检查问题长度、top-k 范围、文档完整性和 active corpus fingerprint。
3. 缓存未命中时，为问题调用 embedding API。
4. PostgreSQL 用 pgvector `<=>` 计算余弦距离，按距离升序取候选。
5. 用 `similarity = 1 - cosine_distance`，过滤低于默认0.30的片段。
6. 校验返回片段与当前审阅文档的原文及 metadata 一致。
7. 返回默认最多3条，最多允许4条，供模型解释并引用。

模型决定工具调用，因此 prompt 仍然可能路由错误。检索函数本身只返回证据，不在内部再调用生成模型写回答。

### 6.4 向量、余弦与 ANN 的基础

Embedding 是将文本映射为固定长度的数值向量，使语义相关文本有机会在向量空间接近。它不是关键词列表，也不是对模型重新训练。

余弦相似度：`dot(q, d) / (norm(q) * norm(d))`。pgvector 负责计算；代码还检查向量维度、有限值和非零范数。

当前16个片段使用**精确向量最近邻搜索**，没有 HNSW/IVFFlat 近似索引。数据量很小时没有必要为了技术栈展示增加 ANN。规模增大后再测量精确搜索耗时，评估 HNSW 的召回、延迟、内存和构建成本。

HNSW 是图索引，通常用额外内存和维护成本换取近似搜索速度；IVFFlat 通过聚类缩小候选范围，需要代表性数据和参数调优。知道概念不代表本项目已经使用。

### 6.5 Fingerprint 为什么比“文件时间变了”更可靠？

当前 fingerprint 包含语料文件 SHA256、embedding 模型、维度和分块/输入配方版本。改变模型或文档，需要显式重新导入；查询遇到不匹配会报告 unavailable，而不是把新查询向量与旧模型向量混用。

元数据改变可能需要新语料版本，但相同 embedding 输入仍可复用既有向量。旧版本保留，没有自动无限历史清理策略。

### 6.6 为什么不能说0.8相似度就是80%正确？

相似度衡量 embedding 空间中的接近程度，不是事实正确率、文档支持概率或答案置信度。默认0.30是启发式过滤值，尚未在正式标注集上校准。

检索到某段文字也不意味着它支持用户的全部前提。模型必须核对证据蕴含关系；不存在支持时应说明范围不足，不能凭相似主题补出医院具体原因。

### 6.7 为什么保留旧全文检索？

它只作为显式配置的 legacy 模式，便于对照和回滚；默认是 vector。向量服务故障时不会静默切到关键词模式。未来可以通过 RRF 融合 BM25 与 vector，利用精确术语匹配和语义匹配各自的优势；当前没有实现自动 hybrid retrieval。

### 6.8 最重要的英文回答

> My RAG corpus contains reviewed methodology documents, not hospital financial rows. During ingestion, I split the text into overlapping passages, embed the title, topic and excerpt, and store the vectors with provenance in pgvector. At query time, I embed the question and run cosine similarity search over the active corpus. I preserve source URLs, PDF pages and version metadata. The corpus is small, so I currently use exact search rather than an approximate index. Similarity is a retrieval signal, not confidence that an answer is correct.

**追问：Does RAG eliminate hallucinations?**

> No. It gives the model relevant evidence, but retrieval can miss the right passage and generation can still misinterpret it. I separate retrieval errors from no-match results, preserve citations and constrain hospital-specific numbers to deterministic tools. I still need a labeled retrieval and answer-faithfulness evaluation set.

### 6.9 下一步怎样评估 RAG？

准备英文、中文、改写、歧义和无法回答的问题集。每题标注支持文档或正确拒答条件。

- Retrieval：Recall@k、Precision@k、MRR，及重复片段占比。
- Generation：事实支持率、引用准确率、引用覆盖率、拒答是否恰当。
- 系统：embedding 和数据库延迟、cache hit rate、每请求 token/cost。
- 对照：lexical、vector、未来 hybrid；固定问题、语料和模型版本。

MRR 是首个相关结果排名倒数的平均值；Recall@k 是相关证据中进入前k的比例；Precision@k 是前k结果中相关的比例。当前仅有离线契约测试和少量实际检索样例，不能报告虚构的召回率或准确率。

## 7. 财务与公共卫生数据：让面试官看到你理解业务

### 7.1 当前公式必须说准确

- 项目 operating margin：`Net Income from Service to Patients / Net Patient Revenue × 100`。这是当前实现使用的 CMS 字段组合，不应泛化为所有机构的统一会计定义。
- Liabilities/assets：`Total Liabilities / Total Assets × 100`。
- Occupancy：`Total Days / Total Bed Days Available × 100`。
- Cost-to-charge ratio：采用报告字段值，不是临时让模型用收入和成本重新估计。

缺失、分母为0或非有限数会影响计算。负资产等情形可能保留带符号的原始比值用于追溯，但 `blocked_metrics` 禁止把该比值作为正常指标排名或解释为改善。不能只检查 `value is not None`。

### 7.2 Year alignment 为什么重要？

CMS dataset year 与实际财政起止日不同。两家医院都出现在2024年数据集中，不代表覆盖相同经营期间。比较需要共同 dataset year，还要检查实际财年。当前直接差值和比较柱状图对财年一致性的要求较严格。

数据质量层使用约330–400天识别近似年度期间；趋势还检查重叠和长度差异。这些是项目启发式规则，不是 CMS 规定的风险规则。

### 7.3 Rural 的定义

使用选定年度 CMS 成本报告的 `Rural Versus Urban` 字段，当前导入值按 R/U 识别，缺失为 unknown。不能用医院名称、县人口或 AHRF/USDA 县级代码替代。

CMS 支付分类与地理农村性可能不同，城市医院也可能获得农村重分类。系统提醒某院在某报告年为 urban 后，仍可继续分析，不能因此拒答或推断其当前所有政策资格。

### 7.4 Access 指标的边界

- Haversine 是经纬度球面直线距离，不是驾车时间。
- 当前候选限制同州；跨州医院可能更近。
- 缺坐标医院被排除，必须报告排除数量。
- 县内医院数量不等于最近医院数量；县内为0不代表附近没有医院。
- 不评估床位容量、服务是否等价、患者资格或能否接收转诊。
- `candidate_count` 已是成功定位参与排名的医院数，不能再减一次 skipped 数量。

### 7.5 县级统计不等于医院患者画像

ACS 人口、保险和贫困是相应县级统计人群；不是医院精确服务区，也不是 Ho-Chunk 部落成员或医院患者。保险覆盖使用 civilian noninstitutionalized population 等具体 universe，不能直接用全县人口作所有分母。

公共保险覆盖率不等于 Medicare/Medicaid 参保明细，公共/私人保险也可重叠。收入中位数使用2024年美元口径。

### 7.6 MOE 与医疗人员比率

ACS MOE 对应90%置信水平；比例的 MOE 单位是百分点。受控估计的 MOE 不适用时保留 null 和状态，不伪造0；也不能只看两个点估计就声称统计显著。

AHRF 医生、牙医字段和 NP/PA 字段可能来自不同年份。当前比率使用对应年度人口分母，存储 numerator/denominator 的变量和年份。NPI 注册人数不是 FTE，也不证明正在接诊。重叠职业类别不能直接相加为“总可用医疗人员”。

## 8. Streaming、前端和图表

### 8.1 当前是 token streaming 吗？

不是。当前 `/agent/chat/stream` 使用 NDJSON 事件流，先发公开进度，随后发 warnings、evidence、context、charts 等事件，最终一次性返回完整模型回答。不能把它描述成逐 token 打字输出。

也不是标准 SSE：媒体类型为 `application/x-ndjson`，每行 JSON；前端用 fetch reader 解析，而不是 EventSource。

### 8.2 线程、Queue 和 ContextVar 的作用

- 每个请求有自己的 Queue 和停止标记。
- 后台 Thread 执行同步 Agent 工作，响应迭代器消费事件。
- ContextVar 将服务进度关联到当前请求，避免不同用户的事件混在一起；结束时 reset。
- 10秒无消息时发送 heartbeat，保持连接活动。
- 前端处理网络 chunk 可能把 JSON 行拆开的情况，不能假设一次 read 就是一条完整消息。

断开连接只停止交付，并不取消已经运行的外部请求。当前线程和 Queue 没有完善的全局并发限制/背压；高并发上线前需要任务容量、取消和超时治理。

### 8.3 图表如何防止模型编造数字？

模型仅选择工具及医院；后端用确定性指标生成绘图 payload，前端 SVG 绘制。每个点保留报告年份、实际财年、来源时间和缺失状态。

支持1–5家医院趋势、最多10年，以及2–5家医院共同年度柱状图。缺失年份断线；被屏蔽指标不绘制；财年不一致的柱状图被暂缓，保留数据表。图表完整点集不写入对话历史。

后端数据图表正确不意味着 LLM 的文字解释一定正确，仍需要生成评估。

### 8.4 前端安全

Markdown、来源、警告和图表标签通过 DOM textContent 等方式构建，不直接执行模型 HTML。模型提供的 `<script>` 不应变成可执行节点。引用来源仍需检查支持关系，安全渲染与事实正确是两个维度。

## 9. 测试、评估和性能

### 9.1 已经验证了什么？

本轮完整指定离线测试集记录为247项测试通过、6项子测试通过，另有前端 Node harness。它们覆盖确定性计算、缺失和异常、身份/历史、流式契约、图表、检索边界及模拟故障。

实际 Supabase 和 embedding 调用还验证了导入、数据库优先读取，以及英文 HPSA、中文误差、CMS 字段和无关问题检索。这些是样例，不是统计意义上的端到端模型 benchmark。

不要声称247个都是模型评测、100%代码覆盖、生产 SLA 或临床验证。仓库部分独立脚本会调用在线服务，不能把所有 `_test.py` 无区别当成离线测试运行。

### 9.2 建议如何分层解释测试？

1. Unit：公式、日期解析、分块、维度和有限值、缺失语义。
2. Service/contract：模拟 CMS/数据库/embedding，检查模式、参数、版本和失败处理。
3. Frontend：图表负值/断线/切换、流式事件和安全文本渲染。
4. Live integration：有限地验证真实连接和数据路径。
5. 尚待系统补齐：自然语言意图路由、回答忠实度、真实用户任务效率和负载评估。

### 9.3 如何定位“为什么这么慢”？

按阶段计时，而不是只看前端 Connecting 文案：

- 请求接入/平台冷启动。
- 首次模型调用和工具选择。
- 每个工具的 DB、HTTP、计算时间。
- RAG query embedding 与 pgvector 查询。
- 最终模型生成、前端接收与渲染。

对每类任务记录冷/热缓存的 p50、p95、失败率、工具调用数和 tokens。隔离更改做前后对照，固定数据版本和输入集。

曾测得单次 WI 名单工具约2.36秒，只能说明那次工具测试，不能当作整个 Agent 的平均响应时间或宣称提升百分比。

### 9.4 已做与未做的性能优化

已做：数据库快照、批量名单分类、有限并发年度查询、连接复用、TTL 缓存、查询 embedding 缓存、短工具输出和有限历史。

未做成完整方案：分布式缓存、请求 tracing、LLM 结果缓存、持久任务队列、物化全部财务/距离结果。不要把曾讨论的方案当作已部署能力。

## 10. 安全、可靠性和生产化取舍

### 10.1 已有控制

参数化 SQL、固定服务查询、读取事务只读、数据库超时、bounded 输入、私有 schema、忽略 `.env` 和运行时缓存、受约束的工具、不可执行的文本渲染。向量检索有模型/版本/维度校验，片段元数据与审阅语料对应。

### 10.2 必须诚实承认的缺口

- 完整用户认证、共享限流、配额/成本上限仍需加强。
- App 可改用最小权限只读数据库账号，导入账号单独管理。
- 非流式错误接口仍有收紧内部错误细节的空间。
- 每请求线程/无界 Queue 的并发和背压不是生产级方案。
- 需要统一 tracing、指标、告警和可执行的备份/恢复流程。
- 需要更系统的 prompt injection、工具滥用与引用忠实度评估。
- `.env` 不提交不等于密钥永不泄露；曾公开或共享过的凭据需要轮换。

### 10.3 Prompt injection 怎么回答？

把用户和检索文档都当作数据。SYSTEM_PROMPT 明确文档不能覆盖指令；历史只允许 user/assistant 角色；工具参数、SQL和计算固定在后端；渲染不执行 HTML。

这些是降低风险的分层措施，不是已证明防住所有攻击。后续应添加恶意文档/问题测试、最小权限和工具调用预算。不要把内容 SHA256 当成 prompt injection 防御本身。

### 10.4 更大规模如何演进？

先测量瓶颈，再按需增加异步 I/O 或有容量限制的后台队列、读写账号分离、共享缓存和限流、数据库高频字段索引/物化表。文档扩大后再增加 ANN、hybrid retrieval 和 reranking，并测量召回与成本。

不需要为了展示技术栈立刻把小原型拆成微服务。单个 FastAPI 服务加明确的模块和后台导入，对当前规模更容易调试。

## 11. 三个可用于行为面试的真实技术故事

### 故事A：简单名单请求却很慢

**问题**：只问5家乡村医院，却可能触发全州可及性分析，包括逐院分类、坐标、距离和县证据。

**改动**：专门增加列表工具及 API，支持州、县、ZIP和 limit；数据库模式批量取分类，避免无关分析。

**验证**：单批查询、地理筛选、未知分类和静态路由测试；真实 DB-only 查询。没有完整端到端 A/B 延迟结论。

**英文：**

> A simple hospital-list request was routed to a much broader access-analysis tool. I traced the extra work and introduced a compact listing tool that batches classification reads and skips geocoding and county evidence. The lesson was that latency can come from tool granularity and orchestration, not just model speed.

### 故事B：看似有效的年度报告被错误拦截

**问题**：CMS CSV 日期为 `MM/DD/YYYY`，质量检查只接受 ISO，正常报表被误标为需要财年复核，图表可能被错误拦截。

**改动**：增加共享日期解析，接受两种格式；用于单年质量和趋势检查，图表比较按日期值判断。

**验证**：覆盖等价格式、实际年度跨度、真实 Supabase 图表结果。注意修复是让有效格式正常通过，没有放松对不同财年的检查。

**英文：**

> The chart workflow exposed a date-format mismatch between imported CSV records and our validation logic. I added a shared parser for CMS and ISO date formats and regression tests for equivalent dates. I kept the comparability rules strict; the fix was in parsing, not in suppressing the warning.

### 故事C：跨州版本指针错误

**问题**：跨州验证发现部分财务覆盖指针关联了错误州/年度的导入记录。不能把尚未确定的根因讲成已查明的 SQL bug。

**改动**：用保留的完整原始 run 修复指针；添加包含州/年度的组合外键，读取 join 也校验 scope。

**验证**：数据库拒绝错误 scope 更新，事务回滚；再核验各州年度行数。

**英文：**

> Cross-state validation revealed that a coverage pointer could reference an import from the wrong scope. I repaired the pointers using preserved complete runs and added composite foreign-key constraints. The important change was moving a scope invariant into the database so application mistakes would be rejected. I would not claim a root cause that I had not established.

## 12. 高频深挖问题：先自己回答，再看提示

1. **Why not let the LLM calculate ratios?** 可重复、可测试、可追溯；模型解释不替代领域公式和输入检查。
2. **Why not use SQL alone?** 固定查询能直接用 SQL；自然语言歧义、任务选择和解释是 Agent 的交互价值。
3. **Why not vectorize every financial row?** 数值筛选、范围和关联需要准确结构化操作；向量相近不保证选对医院/年度。
4. **Why PostgreSQL rather than only SQLite?** 云端共享、事务、约束、连接并发和 pgvector；SQLite仍适合本地可再生缓存。
5. **What is the source of truth?** 配置模式下的 active complete snapshot；它是有日期的源副本，不保证实时官网最新。
6. **How do you choose between duplicate reports?** 复用确定性 primary-row 选择：完整度优先，再以财政结束日期字符串评分；并非已解决所有修订/重复报告语义。日期排序标准化也是可继续改进的地方。
7. **Can the model invent a CCN?** Prompt要求先解析，服务继续验证；工具调用本身仍可能失败，所以不能仅靠提示词。
8. **How do you handle unsupported states?** 明确未导入/未知覆盖，不宣称医院不存在；hybrid是显式选择，不是默认隐藏回退。
9. **What happens if OpenAI embedding fails?** 返回 retrieval unavailable，不伪装 no-match，也不静默词检索。
10. **Why 1536 dimensions?** 默认 small 模型的输出配置，当前成本/规模下够用；没有做维度优化实验，改维度需要 schema和版本一致迁移。
11. **What is top-k?** 最多返回的候选片段数；提高可能增加召回，也增加噪声和 tokens。
12. **Why not HNSW now?** 只有16片段，精确扫描简单且无近似召回损失；规模与实测决定是否增加索引。
13. **Do citations guarantee correctness?** 不保证，要验证引用是否支持具体断言，而不只是相关主题。
14. **Can the system infer a hospital's cause of losses?** 现有字段提供观察指标，不足以证明具体经营原因或因果关系。
15. **Can it analyze tribal clinics?** 可能做历史目录解析或已确认地址的可及性分析；不能把历史诊所编号当成当前医院财务 CCN。
16. **Is memory stored in LangGraph?** 当前主要由浏览器有界历史/身份提供，没有durable checkpointer。
17. **Are tool messages trusted?** 是数据证据；外部内容不能覆盖系统指令，元数据和参数仍需要验证。
18. **How would you prevent rising token usage?** 有界历史、紧凑输出、调用预算、测量每阶段usage；缓存不等于免费生成。
19. **What does streaming improve?** 及时反馈活动和证据；不自动减少底层计算耗时，也不等于token streaming。
20. **What changes before a production launch?** 认证/限流/成本预算、专用权限、观测、负载/取消、评测及恢复验证。

## 13. 几个必须熟悉的基础知识

- **Temperature 与确定性**：较低随机性不能保证模型正确；本项目关键数值确定性来自后端函数。
- **Context window**：模型当前能接收的内容有限，历史和工具结果都占预算；不是无限持久记忆。
- **Tool calling 与 RAG**：前者是让模型选择程序能力；后者是检索证据后辅助生成，RAG在本项目中恰好作为一个工具暴露。
- **Embedding 与 fine-tuning**：前者生成检索表示，后者更新模型参数；本项目没有fine-tune。
- **事务 ACID**：解释原子发布、约束和隔离；不要声称网络下载也由同一ACID事务覆盖。
- **Index**：索引改善特定访问路径，有存储/写入成本；pgvector扩展不代表自动建立ANN索引。
- **Concurrency 与 parallelism**：线程对I/O等待有帮助；不代表Python CPU计算得到无限并行，也可能耗尽DB连接。
- **p50/p95**：中位数与尾延迟分位数，不是平均值；少量手工请求不能可靠估计p95。
- **Correlation 与 causation**：亏损、人口老龄化、HPSA是不同层面的证据，不能组合成未经验证的关闭预测。

## 14. 面试前一周怎么复习？

**第1天：项目介绍。** 不看稿讲1分钟和3分钟版本，画出前端到数据库/模型的请求路径。

**第2天：Agent与记忆。** 读工具注册、SYSTEM_PROMPT、`build_messages`；手动测试新医院覆盖旧指代和模糊名称。

**第3天：数据库。** 解释 active pointer、组合外键、幂等、未覆盖与不存在；看一份raw_record和对应指标。

**第4天：RAG。** 完整复述ingestion/query两条路径，解释cosine、top-k、threshold、exact vs ANN以及失败情形。

**第5天：领域与图表。** 手算一个margin，解释财年和缺失、MOE、HPSA、距离的限制。

**第6天：调试和测试。** 练习三个故事，运行离线测试；清楚每个mock替代了哪一层。

**第7天：模拟面试。** 请对方连续追问“为什么”“如何验证”“失败怎么办”“扩展十倍怎么办”，对未完成内容说清计划而不是假装已实现。

### 自测：不看代码能否回答这十项？

- 一次请求经过哪些函数和外部服务？
- 哪些步骤是模型决策，哪些是确定性代码？
- 当前真正导入了什么范围和年份？
- 一个指标的公式、缺失处理和可比性规则是什么？
- 内存缓存、SQLite和Supabase分别解决什么问题？
- pgvector查询实际使用了什么距离，是否有ANN索引？
- 更新文档/模型后怎样防止向量版本混用？
- 为什么247个测试不能代表247个真实用户任务都正确？
- 为什么进度流不能当成模型推理展示？
- 今天最应该补的生产化/评估缺口是什么？

## 15. 代码导航与复习命令

以下是可直接打开的代码入口；括号中的模块名也可用于编辑器搜索：

- [app/main.py](C:/Users/shang/OneDrive/Desktop/CMU-SV/49-797/rural-hospital-ai-agent/app/main.py)：应用启动和静态前端。
- [app/api/routes.py](C:/Users/shang/OneDrive/Desktop/CMU-SV/49-797/rural-hospital-ai-agent/app/api/routes.py)、[app/agents/agent.py](C:/Users/shang/OneDrive/Desktop/CMU-SV/49-797/rural-hospital-ai-agent/app/agents/agent.py)：HTTP和请求校验。
- [app/agents/hospital_agent.py](C:/Users/shang/OneDrive/Desktop/CMU-SV/49-797/rural-hospital-ai-agent/app/agents/hospital_agent.py)：模型配置、prompt和Agent入口。
- [app/tools/agent_tools.py](C:/Users/shang/OneDrive/Desktop/CMU-SV/49-797/rural-hospital-ai-agent/app/tools/agent_tools.py)：注册工具、参数和紧凑结果。
- [app/services/chat_context.py](C:/Users/shang/OneDrive/Desktop/CMU-SV/49-797/rural-hospital-ai-agent/app/services/chat_context.py)：最近历史与身份。
- [app/services/financial_store.py](C:/Users/shang/OneDrive/Desktop/CMU-SV/49-797/rural-hospital-ai-agent/app/services/financial_store.py)、`reference_store.py`：共享数据、只读连接池和版本。
- [app/services/financial_import_service.py](C:/Users/shang/OneDrive/Desktop/CMU-SV/49-797/rural-hospital-ai-agent/app/services/financial_import_service.py)、`reference_import_service.py`、`county_statistics_import.py`：导入与统计定义。
- [app/tools/financial_tools.py](C:/Users/shang/OneDrive/Desktop/CMU-SV/49-797/rural-hospital-ai-agent/app/tools/financial_tools.py)、`trend_tools.py`、[app/services/data_quality_service.py](C:/Users/shang/OneDrive/Desktop/CMU-SV/49-797/rural-hospital-ai-agent/app/services/data_quality_service.py)：指标、趋势和限制。
- [app/services/methodology_vectors.py](C:/Users/shang/OneDrive/Desktop/CMU-SV/49-797/rural-hospital-ai-agent/app/services/methodology_vectors.py)、`methodology_service.py`：向量RAG与legacy入口。
- [scripts/import_methodology_vectors.py](C:/Users/shang/OneDrive/Desktop/CMU-SV/49-797/rural-hospital-ai-agent/scripts/import_methodology_vectors.py)、[supabase/migrations/202610280001_methodology_vectors.sql](C:/Users/shang/OneDrive/Desktop/CMU-SV/49-797/rural-hospital-ai-agent/supabase/migrations/202610280001_methodology_vectors.sql)：迁移与向量导入。
- [app/services/chat_stream.py](C:/Users/shang/OneDrive/Desktop/CMU-SV/49-797/rural-hospital-ai-agent/app/services/chat_stream.py)、`agent_progress.py`、`evidence_summary.py`：公开事件与来源。
- [app/services/financial_charts.py](C:/Users/shang/OneDrive/Desktop/CMU-SV/49-797/rural-hospital-ai-agent/app/services/financial_charts.py)、[frontend/financial-charts.js](C:/Users/shang/OneDrive/Desktop/CMU-SV/49-797/rural-hospital-ai-agent/frontend/financial-charts.js)：确定性图表数据与SVG。
- `app/tests/`：对照测试了解边界，不要只读成功路径。

本地启动：

```powershell
cd "C:\Users\shang\OneDrive\Desktop\CMU-SV\49-797\rural-hospital-ai-agent"
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

浏览器访问 `http://127.0.0.1:8000/demo/`。

面试前的小型离线复习集：

```powershell
python -m pytest app/tests/methodology_vectors_test.py app/tests/methodology_test.py app/tests/financial_charts_test.py app/tests/data_quality_test.py app/tests/chat_context_test.py app/tests/financial_store_test.py -q
node app/tests/frontend_charts_test.cjs
node app/tests/frontend_comparison_test.cjs frontend
```

不要为了复习随意执行所有导入脚本：它们会写云端数据、调用外部服务，embedding导入还可能计费。先知道脚本做什么，再执行。

## 16. 可以反问面试官的问题

- How does your team evaluate agent reliability beyond successful tool calls?
- What balance do you use between flexible agents and deterministic workflows?
- How do you version retrieval corpora and evaluate changes before deployment?
- Which latency or cost metrics would an intern be expected to improve?
- What does a successful intern project look like in terms of user impact and production ownership?

## 17. 相关项目材料与官方参考

优先依据当前源码核对实现。仓库内较早文档的范围/测试数量可能记录的是历史阶段。

- 项目文档：`README.md`、`docs/code_structure.md`、`docs/financial_database.md`、`docs/reference_database.md`、`docs/data_quality_and_rag.md`、`docs/financial_charts.md`。
- [OpenAI embeddings](https://developers.openai.com/api/docs/guides/embeddings)。
- [Supabase pgvector](https://supabase.com/docs/guides/database/extensions/pgvector)。
- [CMS Cost Reports](https://www.cms.gov/data-research/statistics-trends-and-reports/cost-reports)。
- [ACS Statistical Testing](https://www.census.gov/programs-surveys/acs/guidance/statistical-testing-tool.html)。
- [HRSA AHRF](https://data.hrsa.gov/topics/health-workforce/nchwa/ahrf)。

技术面试最有说服力的不是技术名词数量，而是能说清一个设计解决了什么问题、如何验证、失败时怎样表现，以及当前还不知道什么。
