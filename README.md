# Biaoshu · 标书撰写 Skill + 工具版

从招标文件到技术标草稿的 **Skill 规则 + 可验证 Python 工具**。重点是“技术评分项逐项响应、原文证据可追溯、全局事实一致、分章节写作、机械审查 + 语义终审”。

> 状态：**v0.1 基础闭环**，不是开箱即用的正式投标自动生成器。当前规则用于 Agent 写作，Python CLI 不会自行调用大模型。Word 输出只是基础草稿格式；最终仍需专业与投标合规审核。

## 仓库入口

- [SKILL.md](SKILL.md)：主 Skill，说明任务识别、执行阶段与交付标准
- [references/](references/)：招标解析、事实基线、目录、正文和审核规范
- [biaoshu/](biaoshu/)：Python 命令行工具
- [docs/roadmap.md](docs/roadmap.md)：阶段目标与未完成事项
- [docs/progress.md](docs/progress.md)：迭代记录
- [tests/](tests/)：单元测试

## 快速开始

Python 3.10 或以上。在项目目录执行：

```bash
# 基础功能无需安装第三方包
python -m biaoshu init ./workspaces/my-bid

# 如需读取 PDF、DOCX 或导出 DOCX
python -m pip install -e ".[docs]"

# 从招标文件提取文本；再由 Agent 按 SKILL.md 核实和填充 JSON
python -m biaoshu extract ./tender.pdf --output ./workspaces/my-bid/tender-extracted.md
# 同时生成 tender-extracted.index.json：SHA-256、原文位置、文本块及警告

# 编辑四个 JSON 后进行结构校验
python -m biaoshu check ./workspaces/my-bid

# 生成字数分配、准备章节文件
python -m biaoshu allocate ./workspaces/my-bid --total 12000
python -m biaoshu scaffold ./workspaces/my-bid

# Agent 写入 sections/S1.md 等后，进行严格机械审查
python -m biaoshu audit ./workspaces/my-bid --output ./workspaces/my-bid/reports/audit.json

# 通过审核才能默认导出；也可指定 --draft 生成未完成草稿
python -m biaoshu export ./workspaces/my-bid --output ./output/technical-bid.docx --draft

# 测试
python -m unittest discover -s tests -v
```

## 项目数据格式

工具初始化 project.json、requirements.json、facts.json、outline.json、sections/ 和 reports/。

```json
{
  "requirements": [
    {
      "id": "R1",
      "title": "招标技术评分大项",
      "score": null,
      "evidence": {
        "file": "招标文件.pdf",
        "location": "页码或章节",
        "quote": "需用原文替换的证据占位"
      },
      "response_sections": ["S1"]
    }
  ]
}
```

上面仅是格式示意，不是任何真实招标要求；若缺少真实证据应记录缺失，不能复制示例内容伪造来源。其他 JSON 结构、操作规程见 SKILL.md 和 references/。

## 已实现与限制

已实现：TXT/MD 行定位、PDF 页定位、DOCX 段落与表格行顺序定位、SHA-256 证据索引、评分要求与章节双向映射、证据字段机械检查、事实状态检查、权重与评分分配字数、章节脚手架、基础 Markdown 到 DOCX、CLI、单元测试与 GitHub Actions。

尚未实现：证据引文自动对照索引校验、自动 LLM 写作执行器、PDF OCR、高保真 DOCX 还原、复杂表格与图片处理、自动生成完整专业标书、标准与法规自动核对。机械审查不等于语义审查或合规审查。

**资料隐私**：本仓库为公开仓库。不要提交真实投标文件、项目报价、密钥、企业商业秘密或客户信息；工作区建议保留在本地。真实业务启用云端模型前先确认用户授权和保密要求。

## 来源说明

本项目参考 OpenBidKit 的通用标书撰写方法论，采用独立实现；不直接复制其 AGPL-3.0 代码。后续若希望复用第三方代码，应先检查许可与分发义务。当前尚未决定本项目自身的开源许可证。

## 原文证据校验与导出门禁（开发分支）

`extract` 除了可读 Markdown 还会生成同名的 `.index.json` 证据索引，保留行/页/段落/表格行位置和原文件 SHA-256。应以招标原文为准填充 `requirements.json` 与 `facts.json` 中证据的 `file/location/quote` 字段。

```bash
python -m biaoshu extract ./sources/tender.txt --output ./workspaces/my-bid/tender-extracted.md
python -m biaoshu check ./workspaces/my-bid
python -m biaoshu audit ./workspaces/my-bid --index ./workspaces/my-bid/tender-extracted.index.json --source-dir ./sources --output ./workspaces/my-bid/reports/audit.json
python -m biaoshu export ./workspaces/my-bid --index ./workspaces/my-bid/tender-extracted.index.json --source-dir ./sources --output ./output/technical-bid.docx
python -m biaoshu export ./workspaces/my-bid --draft --output ./output/draft.docx
```

说明：`check` 可不提供证据索引，但结果会明确标记 `not_checked`；`audit` 与非草稿 `export` 必须同时提供 `--index` 和 `--source-dir`，并验证源文件指纹及逐条引用。多份招标文件可重复传入 `--index`。草稿例外仅允许生成显著标识未完成校验的文档，不代表证据可信。文本匹配不能替代评分语义判断、条款完整性检查与人工终审。


## 技术评分项候选（本轮新功能）

先运行 `extract` 建立招标原件的 SHA-256 证据索引，再使用以下命令产生技术评分项候选：

```bash
python -m biaoshu score-candidates --index ./workspaces/my-bid/tender-extracted.index.json --source-dir ./sources --output ./workspaces/my-bid/reports/score-candidates.json
```

索引可通过多次 `--index` 传入，`--source-dir` 必须包含未修改的原始招标文件。每条候选均含原文定位和逐字引用，并标记 `pending_review`。结果的顶层 `status=suggestions_only`，**不会写入 requirements.json**。该工具是保守的规则筛查：对无显式分值、综合分档与复杂表格会漏检；必须由 Agent/人工审查原文，区分技术评分大项与评分规则、商务/报价因素，并补全遗漏后才能形成正式需求。


## 本地 AI 招标分析（待人工确认）

需先执行 `extract` 生成原文索引；本功能使用 OpenAI 兼容的本地推理服务（例如 Ollama），**不自动访问云端模型，也不自动修改正式 requirements.json**。

```bash
# 先在本机独立运行模型服务器，并确认所指定模型已经安装
python -m biaoshu analyze-ai --index ./workspaces/my-bid/tender-extracted.index.json --source-dir ./sources --model YOUR_LOCAL_MODEL --output ./workspaces/my-bid/reports/ai-suggestions.json
```

默认接口是 `http://127.0.0.1:11434/v1`。可用 `--endpoint` 指定另一个 OpenAI 兼容 base URL。为防止机密外传，非本地地址默认被拒绝；仅在确认招标资料及模型服务的授权与隐私政策后，才显式添加 `--allow-remote`，并可通过 `--api-key-env VARIABLE_NAME` 从环境变量读取密钥，切勿把密钥写入命令或仓库。

分析时采用有限长度的来源文本块，输出的 `file/location/quote` 要逐条与实际提供给模型的证据块匹配；原文件改变、生成的引文不符、模型输出非法 JSON 时直接报错，不写正式需求。多份文件重复使用 `--index`。对跳过的块、评分分档、遗漏评分项、实质性条款及法律合规要求，仍须通读原文和人工审稿。输出仅是 `suggestions_only`。


## 人工审核候选并登记正式需求

此前 analyze-ai 和 score-candidates 只生成待审核建议；现可由审稿人审核后建立一一对应的初版技术标章节。

```bash
python -m biaoshu review-init --suggestions ./workspaces/my-bid/reports/ai-suggestions.json --output ./workspaces/my-bid/reports/review.json
# 人工逐项将 decision 修改为 accept/reject，并在核对招标原文后填写 acknowledgement：
# 我已逐项核对招标原文，并确认接受项可登记为技术响应需求
python -m biaoshu review-import ./workspaces/my-bid --suggestions ./workspaces/my-bid/reports/ai-suggestions.json --review ./workspaces/my-bid/reports/review.json --index ./workspaces/my-bid/tender-extracted.index.json --source-dir ./sources --output ./workspaces/my-bid/reports/import-preview.json
# 确认预览后才加 --apply 真实登记
python -m biaoshu review-import ./workspaces/my-bid --suggestions ./workspaces/my-bid/reports/ai-suggestions.json --review ./workspaces/my-bid/reports/review.json --index ./workspaces/my-bid/tender-extracted.index.json --source-dir ./sources --apply
```

默认仅预览。程序核对候选文件的 SHA-256、逐条审批、原件指纹，并重新解析原件对照证据索引；通过后只追加正式需求及一一对应叶子章节，保留已有正文，在本地 reports/review-backups 保存导入前备份。scoring_rule 不允许直接创建章节。人工确认字段是操作者声明，不是身份认证；严禁模型代填。目录目前仅为平面初稿，仍需语义审查及多级规划。


## 层级目录规划与一级目录锁定（开发分支）

在 review-import 产生 R#/S# 响应关系之后，可单独编辑“目录展示树”，不重写 S# 章节或正文：

```bash
python -m biaoshu outline-init ./workspaces/my-bid --output ./workspaces/my-bid/reports/outline-proposal.json
# 手动编辑 outline-proposal.json 的 roots；可将叶子 {"section_id":"S1"}、{"section_id":"S2"} 分组为：
# {"id":"G1","title":"项目实施与进度","children":[{"section_id":"S1"},{"section_id":"S2"}]}
python -m biaoshu outline-plan ./workspaces/my-bid --proposal ./workspaces/my-bid/reports/outline-proposal.json
python -m biaoshu outline-plan ./workspaces/my-bid --proposal ./workspaces/my-bid/reports/outline-proposal.json --apply
# 仅在用户确实确认一级目录后显式执行：
python -m biaoshu outline-lock ./workspaces/my-bid --confirm
```

自动验证目录节点、唯一章节覆盖、深度不超过 4 层、拒绝无意义单子节点分组；默认预览不修改文件，明确 --apply 后才写 outline.json，先备份至 reports/outline-backups。层级 Word 导出按树的顺序生成标题。锁定将保护一级节点名称、顺序及其对应章节集合，允许组内下级排序调整。check、audit、export 均检查目录锁；即使 --draft 也不能导出损坏的层级树。

如果已经建立层级目录，review-import 会拒绝直接追加新的 S# 章节，避免遗漏映射或丢失用户确认的目录；需先审查并调整目录结构。该功能为**结构编辑与锁定**，尚非基于模型的自动语义目录规划。目录锁属于本地防误改约束，不是数字签名或抗恶意篡改方案。


## AI 分章节草稿生成与人工核准（开发分支）

使用已登记的需求和真实原件证据，为每个稳定 S# 章节生成单独草稿，默认使用本机 OpenAI 兼容模型。模型不会自动获得未核实事实的具体值。

```bash
python -m biaoshu write-sections ./workspaces/my-bid --section S1 --index ./workspaces/my-bid/tender-extracted.index.json --source-dir ./sources --model YOUR_LOCAL_MODEL
# 不指定 --section 时按当前目录树顺序执行所有章节；每个章节有独立检查点。
# 由审稿人亲自核对 S1 正文、评分响应、原文数字和实际承诺，然后执行：
python -m biaoshu approve-section ./workspaces/my-bid --section S1 --acknowledgement "我已逐项核对本节事实、招标响应和承诺，并批准该正文"
python -m biaoshu audit ./workspaces/my-bid --index ./workspaces/my-bid/tender-extracted.index.json --source-dir ./sources
```

章节只在缺失或恰为 scaffold 自动生成的 TODO 占位时写入；已经存在的人工正文及已有 AI 草稿一律跳过，重复执行可续写未完成章节。模型调用失败时记录本地失败检查点，不保存提示词或密钥。输出的 AI 草稿带有待审查提示；严格 audit 与非草稿 export 在章节未批准或批准后内容变化时阻断。审批确认是操作者声明，而非签名或完整语义核验。不得让模型代替人执行批准。

默认本地接口 http://127.0.0.1:11434/v1；远程仅在资料外发已获合法授权并显式加 --allow-remote 时启用。AI 只检验引用过的原文文本存在且模型声明覆盖本节要求，并不保证语义完全覆盖、事实绝不遗漏、标书可正式投标。真实模型兼容性和长文质量有待专项验收。


## 跨章节承诺一致性审查（本轮新增）

在章节完成后执行本地机械核验，重点定位各章节对明确的工期、服务期限、质保期和响应时限的互相矛盾：

```bash
python -m biaoshu consistency-audit ./workspaces/my-bid --output ./workspaces/my-bid/reports/consistency.json
python -m biaoshu check ./workspaces/my-bid
python -m biaoshu audit ./workspaces/my-bid --index ./workspaces/my-bid/tender-extracted.index.json --source-dir ./sources
```

报告包含逐条冲突的章节 ID、行号、原句、数值与单位，也会将相同字段与 facts.json 中已核实的唯一基线值核对。未确认事实出现确定性承诺时标记 warning。普通 check 只警告，严格 audit 和正式 export 会阻断同单位下明确矛盾；草稿导出仍须明确标识未校验状态。扫描只读取本地章节，不请求远程服务也不会自动改写正文。

本工具仅对这四种带明确单位的等式型承诺做保守文字核对，不比较不同单位或专业条件、上下限，不保证发现所有项目事实与评分项漏写，不替代独立语义审稿、合规审核与人工终审。


## 跨模块脱敏端到端验收

新增 `tests/test_pipeline_e2e.py`：完全使用虚构 TXT 与模拟模型，实际调用 `init/extract/score-candidates/analyze-ai/review-init/review-import/outline-init/outline-plan/outline-lock/allocate/scaffold/write-sections/approve-section/consistency-audit/audit/export` 等生产 CLI，并验证真实 DOCX 生成及失败恢复。详见 [验收说明](docs/e2e-acceptance.md)。本测试**不表示人工已审稿或真实投标项目已验收**。


## 技术评分项到正文原句的追溯台账（v0.9）

完成章节写作、审核并确认正文稳定后，可将每一个评分要求与实际响应原句建立**人工逐条复核**的定位记录：

```bash
python -m biaoshu trace-init ./workspaces/my-bid
# 由审稿人在 reports/response-trace.json 为每条需求→章节映射填写：
# line（正文行号，从1开始）、quote（该行实际响应原句，长度至少12字符）、decision=confirmed。
# 审稿人亲自填写 acknowledgement：
# 我已逐项核对评分要求和正文段落，并确认上述定位引用为实际技术响应
python -m biaoshu trace-audit ./workspaces/my-bid --output ./workspaces/my-bid/reports/trace-audit.json
python -m biaoshu audit ./workspaces/my-bid --index ./workspaces/my-bid/tender-extracted.index.json --source-dir ./sources
```

trace-init 不会覆盖已有审核台账，初始全部 pending；trace-audit 只读检查每个要求的章节映射、Markdown 行号、逐字原句、正文 SHA-256，以及明确人工确认。不能把标题、表格引用、引文块或过短片段当成有效响应。对需求标题、章节映射和正文修改均要求重新审核。

为兼容之前的本地项目，**未启用追溯台账时** strict audit 仍可运行，但会明确警告“尚未建立正文追溯”；**启用台账后**，尚未人工确认、遗漏关系、正文变化或无效定位将使严格 audit 和非草稿 export 失败。追溯通过只说明引用位置存在且操作者声称已核实，不证明实际满足评分条款、没有遗漏专业义务或已经完成法律合规审核。


## AI 独立语义审稿（新增，必须人工复核）

当 `trace-audit` 已通过、招标原件索引可核验时，可使用**明确指定的本地模型**逐条比对评分要求与人工定位的实际响应段落：

```bash
python -m biaoshu semantic-review ./workspaces/my-bid --index ./workspaces/my-bid/tender-extracted.index.json --source-dir ./sources --model YOUR_LOCAL_MODEL --output ./workspaces/my-bid/reports/semantic-review.json
```

默认使用本机 `http://127.0.0.1:11434/v1`；模型接口必须 OpenAI 兼容，且支持 JSON 格式响应。远程地址默认禁止，真实资料外发须先获得授权并显式添加 `--allow-remote`，可通过 `--api-key-env` 从环境变量读取密钥。

审稿结果是 `suggestions_only`，按每个 `requirement_id + section_id + section_line` 列出 `adequate/partial/missing/uncertain`、风险级别、原因、修订建议、真实原文和正文引文，并逐一标记 `pending_human_review`。模块在调用前验证原件 SHA-256、重新解析索引并检查已确认响应台账；验证生成的双侧引文确实来自提供给模型的原句，调用后再次检查台账、正文和招标原件未变化。**不会自动批准、重写或覆盖任何项目正文；已有报告禁止覆盖。**

该能力是逐项**局部段落**语义建议，不会独立检查全文评分完整性、综合档次和合规性；即使模型判定 adequate，也绝不意味着该评分项已通过专业审核。


## PR #1—#10 集成准备审查

在合并到 main 之前，请先阅读 [集成准备与高风险阻断清单](docs/integration-readiness-20261015.md)。已确认旧 PR 虽 CI 通过、无 Git 冲突，仍有 P1/P2 自动审查问题；当前加固分支解决来源索引伪造、本地模型环境代理、未批准草稿和部分合同期限边界问题。**尚未获得独立 Approved 审查，不应直接用于生产或正式投标。**
