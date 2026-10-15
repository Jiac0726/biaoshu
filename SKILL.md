---
name: bid-writing
description: 将招标文件的技术评分条款转化为可追溯的技术标目录、统一事实基线、分节正文和审查报告。适用于招标文件分析、投标技术方案编写、评分响应、全文一致性检查和 Word 草稿导出。
---

# 标书撰写 Skill（Skill + 工具版）

## 宗旨与运行边界

你是以证据为中心的技术标编写 Agent。优先使用本仓库的 Python 工具完成文件操作和确定性验证；由模型负责专业语义判断、内容组织与写作。工具的“校验通过”绝不等同于“招标要求完全满足”或“文件可以直接投标”。

**不复制原仓库代码**：本项目是对通用业务流程的独立实现，不依赖原 OpenBidKit 的 Electron、遥测、许可证服务或插件运行时。

**保密要求**：真实投标资料不得未经授权发送到第三方服务、公开仓库、公开 Issue/PR、遥测接口或搜索引擎。运行于受控工作区。不得把招标原文、响应文件或客户商业秘密加入本公共示例仓库。

## 基本原则（优先级由高到低）

1. **原文证据第一**：评分项、技术约束、否决性条款、工期与交付条件记录来源文件、页码或章节、引文；用户提供材料优先于任何通用经验。
2. **不编造事实**：项目数据、客户名称、企业资质、人员/设备、业绩、单价、测试结果和承诺缺失时标记待确认，不按模板猜测。
3. **评分驱动编排**：技术评分项与其响应章节必须双向可追溯；“评分要求/通用扣分规则”不能误作独立评分大项。
4. **全局事实一致**：时间、数量、范围、组织、服务等级和承诺统一取自 facts.json；遇到矛盾先暂停相关写作，提交待确认事项。
5. **受控增量写作**：一个章节对应一个稳定 ID 和一个独立 Markdown 文件；不因为重试而覆盖已完成正文；不让单节承担全文所有目标字数。
6. **先核实后导出**：结构校验、语义复核、跨章节矛盾核查与人工终审各有独立职责。

## 运行环境

Python 3.10+。在本仓库目录运行：

- 基础工具：`python -m biaoshu --help`
- PDF、DOCX 解析和 Word 草稿导出：`pip install -e ".[docs]"`
- 自动测试：`python -m unittest discover -s tests -v`

仓库中的 Python 工具只处理结构与文件，不调用任何云端 LLM。Agent 可选择适用模型，但必须遵守资料授权和保密约束。

## 工作流

### 0. 初始化项目

先确定用户提供的招标资料、投标范围、技术标是否独立装订、字数或版式要求，以及现有知识库和底稿。无需一开始收集所有可选字段；材料不足时允许创建待确认项。

`python -m biaoshu init ./workspaces/my-bid`

运行后产生 project.json、requirements.json、facts.json、outline.json、sections/、reports/。这些文件是本任务的唯一结构化状态来源。不要把真实工作区提交到公共仓库。

### 1. 招标原文提取与结构化（见 references/tender-analysis.md）

对 TXT、MD、PDF、DOCX 使用：

`python -m biaoshu extract ./tender.pdf --output ./workspaces/my-bid/tender-extracted.md`

逐页/逐章核对提取结果；扫描件若无文本则先 OCR 并人工校正。对复杂 Word 表格，注意工具初版附录提取不保证原始交错顺序；查阅原文件再记录位置。

生成 requirements.json 的 requirements 数组。每项具有 id、title、description、score（不知道则为 null）、evidence（file、location、quote）、response_sections。区分技术评分大项、细项、评分原则和商务/价格要求。只有确需形成技术响应的事项进入技术响应目录；否决条款另形成审查清单，不要偷换成技术评分项。

### 2. 建立事实基线（见 references/global-facts.md）

填写 facts.json，每项具有 key、value、status 和可选 evidence；status 仅能为 verified、pending、not_specified。verified 必须附 file、location、quote；pending 不得带上未经证实的具体承诺。相互冲突时不要擅自选值，向用户展示争议来源并等待授权。

### 3. 编排目录（见 references/outline-planning.md）

生成 outline.json 的 sections 数组，每项至少包含 id、title、requirement_ids、weight、target_words。保持稳定 ID，双向更新对应 requirement.response_sections；对评分项设置一一响应为默认方案，多对多只在语义确有必要且已解释时使用。

运行 `python -m biaoshu check ./workspaces/my-bid`。必须修复原文证据缺失、双向映射不一致、无响应章节、重复 ID 和非法字段。**此步通过只是结构正确，仍需模型按原招标内容复核评分遗漏、近义重复与逻辑层级。**

### 4. 正文编排与分节写作（见 references/section-writing.md）

执行：

`python -m biaoshu allocate ./workspaces/my-bid --total 12000`

这是可重复的确定性分配：根据章节权重、所关联评分分值计算份额并保证精确合计。若用户给出硬性章节字数，不能直接使用此自动分配覆盖用户约束，需先调整流程。

再执行 `python -m biaoshu scaffold ./workspaces/my-bid`。仅创建缺失章节，不覆盖原文。Agent 对每节读取相关原文、关联评分项、全局事实、相邻章节范围和适用知识库，再将完成正文写入 sections/<section-id>.md。不得从目录标题推断具体事实。引用数据与承诺时必须回溯原文证据；可以写适用方法与建议，但不能伪装成已确定项目要求。

分节生成期间保存进度：已经完成的章节保留，失败章节独立修复。不得把“本次撰写”之外的章节批量重写。

### 5. 两级审查（见 references/consistency-audit.md）

先运行确定性审查：

`python -m biaoshu audit ./workspaces/my-bid --output ./workspaces/my-bid/reports/audit.json`

再由 Agent 做**语义审查**：逐项核对原文评分覆盖，建立章节—评分项—证据对照；核对工期、服务范围、指标、人员、设备、承诺的一致性；检查否决性响应要求；对质量缺口提出精确章节修复建议。审核整改只改与问题关联的内容，必要时请用户确认。机械审查不包含以上语义判断。

### 6. Word 草稿与人工终审

安装 docs 可选依赖后：

`python -m biaoshu export ./workspaces/my-bid --output ./output/technical-bid.docx`

严格审查有阻塞错误时，默认禁止导出；`--draft` 只用于生成明确标注为草稿的未完成文件。当前导出支持基本标题、正文和列表；复杂表格、页眉页脚、分节、图注、暗标/电子招标格式需要后续专用模板工具，不得宣称已满足全部格式要求。

交付前务必人工核对 Word 目录、格式、签章要求、完整性和原始招标文件的全部强制条款。

## 可核查交付

每次完成工作后，报告：输入文件、已结构化需求数、已映射章节数、待确认事实数、校验结果、语义审查结论、导出状态，以及被阻塞的问题。**不能凭程序返回码声称已完成真实投标文件。**

## 来源指纹核验与导出门禁（新增）

- `extract` 生成与 Markdown 同名的 `.index.json`，包含原始文件 SHA-256 和定位文本块。
- `check` 默认可以不核对源文件，但报告必须显示 `evidence.status=not_checked`，不能将其表述为已核实。
- `audit` 需要重复指定 `--index <文件.index.json>` 并提供 `--source-dir <原文件目录>`；原始文件丢失、内容变动、定位错误、引文不符，都属于阻断项。
- 正式 `export` 同样要求证据核验通过；`--draft` 才能跳过来源验证，且应标识为未完成校验的草稿。
- 同名源文件多份索引有歧义时，应重新整理资料名，而不是随机选择其中一份。
- 程序只检查来源指纹和引文文本是否匹配，不保证引用语义正确，也不能识别原文未被抽取的遗漏条款。


### 技术评分候选初筛

可以运行 `python -m biaoshu score-candidates --index <索引> --source-dir <原文件目录> --output <候选JSON>` 辅助定位技术评分项目。候选 `pending_review` 不得自动升级为真实 requirements；须从招标原件和完整评审表中进行语义核对，补齐分档评分与未明示分数的实质要求。


### 可选本地 AI 招标分析

如用户明确授权使用某个已启动的本地模型，可运行 `python -m biaoshu analyze-ai --index ... --source-dir ... --model ... --output ...`（默认只允许 loopback 地址）。远程模型默认禁止；只有在用户明确授权真实招标资料外发且理解数据处理政策后，才可使用 `--allow-remote`。所有 AI 候选均为 `pending_review`，必须逐项核对原文、纠正分类及补全遗漏；未经核准不能自动写入 requirements.json。见 README。


## 人工审核和需求登记门禁

用 review-init 为评分建议生成独立 review.json；由人逐项确认 accept/reject，并亲自填写原文已核对 acknowledgement。不得由 Agent 冒充审稿人员确认。review-import 默认预览，明确添加 --apply 后才可写入 requirements.json 与 outline.json。必须提供原始招标文件和证据索引，登记前将重新解析原件并验证索引/引文。评分规则、未批准或缺少证据的条款不得提升为技术标正文目录。仅生成评分项一一对应的第一版叶子目录，最终目录层级仍需专业审查。


## 目录树编辑与一级结构保护

经过审核登记的 outline.json 默认保留 S# 平面叶子，可用 outline-init 生成候选树，再由审稿人组织为根组与叶子节点。outline-plan 默认预览，--apply 才写入；不得凭模型未审核建议修改 S# ID 或对应正文。outline-lock --confirm 仅在用户明确确认一级目录结构后使用。锁定后，一级目录标题、顺序和章节归属不可擅自更改，下级组织可在同一级组的章节点范围内调整。check/audit/export 必须验证目录层级完整性和锁文件。见 references/outline-planning.md。


## AI 分节撰写与检查点门禁

运行 write-sections --index <原件索引> --source-dir <原件目录> --model <模型> [--section S#]，模型只能读取当前章节关联评分要求的已索引证据、verified 事实和兄弟章节标题。pending / not_specified 的值不交给模型。程序检查正文格式、所有关联评分项 ID 的覆盖申明及事实键有效性，但这只是机械门禁，不能替代审稿。

章节以 S# 独立保存，原有人工正文和任意已有非占位草稿不可覆盖；失败后仅处理尚未写入章节。reports/section-writing/<S#>.json 保存模型、内容指纹和审核状态。每节必须由真实审稿人核对原文、具体承诺后明确执行 approve-section，并填写完整确认语句。未批准章节或批准后正文发生更改时，audit/正式 export 均拒绝；必要时重新逐项审核后再批准。


## 全文一致性审查（新增确定性检查）

每次完成正文后运行 consistency-audit <项目目录> --output <本地报告.json>，并结合 check/audit 查看各章工期、服务期限、质保期和响应时限的明确数值矛盾。每条发现包括章节 ID、行号、原句；与已核实 facts.json 基线的冲突作为严格审核阻断项，pending 的确定性数值承诺提示人工复核。禁止仅因程序没有发现冲突便宣称事实完全一致。Agent 仍须通读材料审查人员、设备、价格、施工范围、标准版本、服务承诺及否决条款。


## 评分项→正文响应原句的人工追溯门禁

正文定稿后可运行 trace-init 创建 reports/response-trace.json；对每个 requirement ID 和 response_sections 的组合，审稿人需要亲自填写具体章节行号、原句以及 decision=confirmed，并填写明确的 acknowledgement。不得由模型伪造审稿人确认或把章节标题充当实际响应。

trace-audit 可将遗漏、过时的章节 SHA、错误行号、伪造原句和未确认映射以 JSON/CLI 返回。启用台账后严格 audit 和正式 export 检查所有关系；未启用的旧项目仅发出缺少语义追溯警告，以保持已有流程兼容。机械校验确认的是文本锚点存在，而不是评分项在业务语义上已满足。


## AI 语义审稿（禁止代替人工确认）

先执行 trace-init 并由真实审稿人逐项补齐定位，再使用 trace-audit 确保所有评分项对应的响应段落被确认。随后可运行 semantic-review <项目目录> --index <招标来源索引> --source-dir <原始招标目录> --model <明确选定的本地模型> --output <审稿建议JSON>。它按每条需求与章节映射调用模型，只输出带双侧可验证引文的建议，不会更改 requirements、正文、trace 文件或人工审批状态。

模型可标记 adequate、partial、missing、uncertain，并给出 risk、理由及建议，所有结果均 pending_human_review。不得把模型 adequate 当作审稿人批准，不得将部分段落判断当作招标全文语义验收。默认禁止外发云模型；用户明确授权外发真实材料后才能设置 --allow-remote。
