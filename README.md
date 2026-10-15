# Biaoshu · 标书撰写 Skill + 工具版

## 本地 Web 工作台（开发分支）

**状态：Web MVP 位于 feat/local-web-studio-20261015；尚未并入 main 或 V1 RC。**

### Windows 启动

```powershell
git fetch origin
git switch --track origin/feat/local-web-studio-20261015
py -m pip install -e ".[docs]"
py -m biaoshu.webapp
```

启动后自动打开浏览器，也可手动访问 http://127.0.0.1:8765 。关闭使用 Ctrl+C。首次安装好依赖后，Windows 也可以直接双击仓库根目录的 start-web.cmd 启动。

可选：

```powershell
py -m biaoshu.webapp --port 8765 --workspace "D:\标书私有工作区" --no-browser
```

默认工作区 workspaces/web 被 Git 忽略。真实客户资料建议使用仓库外的受控工作区，禁止上传公开仓库。

### 浏览器操作流程

1. 新建项目，上传 PDF/DOCX/TXT/MD 原件并点击“解析原件”，建立 SHA-256 证据索引。
2. 点击“提取评分候选”运行离线规则，或填写本地模型名称后点击“本地 AI 分析”。默认 OpenAI 兼容地址 http://127.0.0.1:11434/v1 。
3. 点击“创建审核清单”，逐条阅读招标原文、选择接受或拒绝，处理多档评分，保存人工审核决定；先预览再确认登记正式需求。
4. 创建目录候选、编辑 roots JSON、应用/锁定层级；分配字数、生成章节，人工逐章阅读并批准。
5. 运行检查与审计，导出带未校验标记的 Word 草稿或通过严格门禁的正式 Word。

评分响应追溯台账可在网页中逐项填写章节行号、响应原句并人工确认；复杂文档模板依旧需要专业人工处理。

### 隐私与限制

- 服务器只监听 127.0.0.1；使用随机会话令牌防跨站写入，拒绝不匹配 Origin 和 Host。
- Web 不提供远程 LLM 开关；底层默认只接受本机模型地址。请勿使用反向代理暴露到网络。
- 单文件最大 40MB，每个项目最多 15 份文件；没有多用户身份系统。
- 长时间 AI 任务需要保持网页和本地服务运行，不支持后台队列。未实现扫描件 OCR、复杂模板、暗标合规与真实投标质量担保。

---

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

## 审核登记中断恢复（集成加固）

`review-import --apply` 现在会在同一工作区中使用独占锁、原始文件备份和持久化事务标记保护 `requirements.json` / `outline.json`。两文件不能在通用文件系统上整体原子替换，因此若更新过程中进程崩溃，`check`、严格审计与正式导出将阻断，直到恢复完成。仅普通协作导入遵守此锁，外部编辑工具仍应避免同时改动文件。

```bash
python -m biaoshu review-recover ./workspaces/my-bid --confirm
```

恢复命令仅当现存两个文件均与日志中的更新前/更新后指纹一致、且备份可核验时，才回退至事务开始前状态；检测到人工或其它程序修改即拒绝覆盖，保留日志供手工处理。恢复后的旧审核决策可重新预览，但已留下的历史备份不会自动删除，以防冲销审计证据。此机制用于中断后的可检测与恢复，并不保证两文件在任意外部进程读取时瞬间一致。

## 集成候选阶段：三项阻断修复（2026-10-15）

- 评分项多档分数（如“合格 5 分、优秀 10 分”）现在在 `score-candidates` JSON 的 `ambiguous_candidates` 中保存真实原文位置、数值选项和人工待审状态，不再静默漏掉，也不生成可直接批准的单一 score。
- 一级目录锁现在包括 **root 直接叶子章节的标题**；锁定后直接编辑对应 section 的 title 会导致 `check/audit/export` 校验失败。旧式缺少该标题的一级目录锁需要审核后重新建立，禁止无声放行。
- AI 章节生成采用 `reports/section-writing/S#.transaction.json` 写前日志；即使两文件写入中途崩溃，项目审计与正式导出都会拦截。检查恢复前后的字节指纹，拒绝覆盖未知人工编辑。

```bash
# 在确认 AI 写作进程已退出、事务确实中断后恢复章节：
python -m biaoshu section-recover ./workspaces/my-bid --section S1 --confirm
# 如进程异常退出并遗留 .write.lock，先确认无进程仍在写，再显式：
python -m biaoshu section-recover ./workspaces/my-bid --section S1 --confirm --unlock-stale
```

恢复动作回退本轮写入的 Markdown 与审核 checkpoint 两份文件，再允许重新生成草稿；绝不替代人工确认。日志缺失而仅有残留锁时不会自动删除锁，需人工检查进程和工作区。以上属于失败检测/保守回退，不是多文件硬件原子事务。


## 评分多档结果必须审核（P1 修复）

`score-candidates` 输出的 `ambiguous_candidates` 不等于忽略的条款：`review-init` 会建立对应 `ambiguous_decisions`，默认 `pending`。只要有未处理的多档项目，`review-import --apply` 就会拒绝导入。人工可以填写 `not_applicable`（需至少 12 字原因），或先在 `requirements.json` 中完整登记对应原文证据，再选择 `manually_registered`。系统会检验该证据确实存在；不能仅凭口头确认自动漏掉多档评分。

目录锁会对一级章节标题损坏返回明确错误；AI 已批准章节的正文/事实变化不能通过再次运行批准命令重签。新建 AI 正文使用先写临时文件、再原子创建目标路径的方式，避免残留半写入文件。

## 离线 Release Candidate 集成验收

建立在 PR #12 已测试快照上的独立 `release/rc-integration-validation-20261015` 分支提供可重复执行的 `python scripts/validate_release_candidate.py`，依次核验全部 unittest、虚构标书端到端 Word 生成和 CLI 启动。详见 [验收清单](docs/release-candidate-20261015.md)。这并非真实模型质量测试，也不表示 PR 已获独立批准或合并主分支。


## P1 审查消项与通用期限键

[审查追溯矩阵](docs/p1-review-closure-20261015.md) 已将原始 PR #1/#3/#6/#7 的 12 条 P1 风险逐一映射到累积版本的具体修复代码与回归测试。

历史数据如使用 `facts.json` 中的泛化期限键 `duration` / `period` / `期限` / `时长`，并标记 `verified`，现在需要显式声明 `category` 为 `project_duration`、`service_duration`、`warranty_duration` 或 `response_time`。未声明会返回 `ambiguous_verified_duration` 并阻断严格审核，不会未经事实支持将通用期限擅自对应某一合同义务。

此变更是失败关闭的兼容性变更，旧项目需人工确认期限类型后才能通过正式导出；仍需独立代码审查与合规验收。

## 模型完成状态与审核输出保护（v0.15）

所有调用统一 OpenAI 兼容聊天接口的 AI 招标分析、章节写作和逐项语义审稿，均检查响应的 `finish_reason`。只有 `stop`（或明确支持的 `eos_token`）代表本次消息正常完成；`length`、`tool_calls`、null、缺失或不合法值均拒绝，**即使消息恰好是可解析的 JSON**，也不能被当作经过审核的完整结果。本地不兼容的后端应修复响应协议，不以忽略完成状态绕过检查。

`analyze-ai`、`semantic-review`、`score-candidates`、`review-init`、`outline-init` 的输出现在采取双重保护：在执行模型或分析前拒绝正式项目/审核文件名及已有路径，完成后以同目录临时文件、原子独占创建，不能覆盖旧报告、招标原文、证据索引或项目配置。输出目标已有文件时，请明确指定新路径，不要依赖自动覆盖。这个保护不会让审稿建议自动提升为人工批准。


### 期限类别在 AI 写作提示中的保真

人工核实的通用期限事实（如 `{"key":"duration","category":"service_duration","status":"verified","value":"30日"}`）在进入章节写作提示时保留 `category`，并明确告知模型不能将服务期限当作项目工期或质保期。对泛化期限事实缺失类别、类别无效的情况会在模型调用前拒绝生成。此项为来源约束检查，不保证模型一定能正确理解所有专业条款，仍需人工确认。

## AI 招标评分证据回收与数值核验（第十六轮）

`analyze-ai` 对超过 3000 字的 PDF 页/DOCX 表格行不再静默只送出前缀，而是切成最多 3000 字、相邻片段保留 160 字重叠的原文切片；筛选和排序按片段分别进行。报告保留未选片段计数和长原文拆分警告。真正跨片段的条款仍可能需要人工全文复核，不能由切片代表已穷尽全部招标要求。

短评分条目即使没有通用“技术、实施”等关键词，只要包含真正的 `5分` 等分值也会进入候选分析；`30分钟` 不再作为 `30分` 提升排序。AI 的非空 `score` 必须与它所引原句中的单一分值一致；`合格5分/优秀10分` 等多个不同档次必须为 `null`，由审核人员裁定。所有 PDF/DOCX/TXT 原文索引中的提取警告会带文件名进入分析报告，提醒核对扫描页、页眉或复杂排版。AI 候选仍只是待人工核实建议。

## 人工评分细则分档与加扣分保护（PR #17）

确定性 `score-candidates` 在读取 DOCX 表格时会把同一单元格中的换行评分档次视作**同一个原文评分条款**，例如“合格 5 分、优秀 10 分”不会直接生成 5 分技术要求。按项目加减分（如“每缺一项扣 2 分”“每增加一项加 2 分”）会进入 `ambiguous_candidates`，标记 `reason=adjustment_rule`，供真正审稿人员逐项处理；不得将 2 分当作项目整体技术评分或自动登记正式分值。技术评分表的“技术评分”类别列会被跳过，优先采用实际响应事项所在列。

`review-init` 和 `review-import` 继续强制对这些候选产生逐项审核决定，未决定不能导入；人工审核输入仅接受 `schema_version=1`。如相同原文证据被再次提交，但评分或条款类型改变，会明确报冲突而非悄悄保留旧分数。多档或加扣分仍需核查原始文件的评分规则与完整上下文。

### 评分引用不能截短规避多档规则（P1 修复）

从 AI 模型返回的 quote 仅用于定位原文，不能让模型通过“只引用优秀 10 分”掩盖同一评分行的“合格 5 分”。数值判断会按经原件 SHA-256 与重新提取验证过的完整评分行核对，DOCX 表格行按整行审查；不同评分档次必须保持 score=null 供审稿人员核实。全角数字及小数先进行 NFKC 规范化再匹配，不会把“５．５分”读成“５分”。“30分内到场”等简称时限不能用于评分候选排序或给出30分评分；纯商务/报价得分不占优先候选的筛选预算。

原文来源索引中的警告字段同样必须与重新提取结果一致，不能私自删除扫描页、PDF 顺序或 DOCX 未覆盖字段的风险提示。测试使用虚构 TXT/DOCX 与模拟模型，不代表复杂招标评分语义已通过人工验收。

## 审核导入报告与正式提交状态（PR #18）

`review-import --apply --output /path/to/report.json` 现在先检查报告路径是否为已有文件、正式项目文件或其他不可用目标，避免在提交数据后才发现目标早已存在。正式审核导入仍由项目独占锁、前后项目快照与持久化双文件事务保护。如果外部编辑器在解析来源期间更改 `requirements.json` 或 `outline.json`，将拒绝将旧内存状态覆盖到新文件。

如果两个正式文件已经成功提交，**但独立报告保存因权限/路径/并发问题失败**，CLI 会输出明确的警告：“已提交成功，但报告未保存”，同时继续报告正式导入状态，而不会谎称需求登记失败导致操作者重复导入。此时请以项目正式文件与 `reports/review-backups` 备份为准人工核对，并另行生成审查记录，不要盲目重试。

已有层级 `roots` 的目录不能直接追加新章，`review-import` 在预览阶段就返回 `blocked_hierarchical_outline` 而不是 `ready`。这类冲突必须先由真实审稿人调整目录结构，不可自动突破一级目录锁。

## 第十九轮：目录备份与审核预览

- outline-plan --apply：历史目录状态 A→B→A→C 时，如备份文件的内容与预期一致，安全复用不可变历史备份；如果内容不同则拒绝覆盖。
- sections[].id 错误为 JSON 数组或对象时，check 返回结构化校验错误而非 TypeError，严格审核继续阻断。
- roots=null 与未构建层级树等价，允许普通导入；真实层级树中的新增章节未分配时，预览直接打印阻断并以非零状态退出。
- review-import --apply 对已登记条目显示“已登记（无新增）”；无新项显示“审核操作完成（无新增）”，不再误显示“仅预览”。
- 人工导入用类型敏感的规范 JSON 校验并发修改：1→true 不会因为 Python 中 1==True 而绕过校验。
- 这些保障不等于跨所有外部编辑器的数据库 ACID 隔离；在正式文件导入期间仍应避免其他程序并行修改。


## 第20轮：AI 章节失败、人工接管与审批中断恢复

章节生成失败而没有写入 AI 正文时，操作者可先手动完成 sections/S1.md，确认正文没有 TODO 或 AI 待审标记，再明确执行以下命令归档失败检查点：

```powershell
python -m biaoshu section-manual ./workspaces/my-bid --section S1 --confirm
```

系统将失败检查点存入 reports/section-writing/archive/，不会把人工正文认作 AI 已批准草稿，也不会修改其他章节。只有失败且从未提交的 AI 章节允许接管；若仍有 AI 草稿待审标记或中断事务则必须先走原有审查、恢复流程。

章节人工批准现在使用与 AI 草稿生成相同的写前事务日志：即使正文去掉待审标记后，审批检查点写入失败，项目仍会被严格审核拦截。确认旧进程终止后，可用下列命令回滚至带标记的待审核草稿，再重新执行 approve-section：

```powershell
python -m biaoshu section-recover ./workspaces/my-bid --section S1 --confirm
```

如果只有孤立 .write.lock、没有事务日志，操作员必须确认进程已经退出，才能同时传 --confirm --unlock-stale。新写作锁包含进程 PID；能证明 PID 仍活动时拒绝清理。绝不可将锁清除当成自动批准或跳过人工复核。双文件写入仅具备日志检测与可核验回退，不是硬件原子事务。


## 第21轮：跨章节冲突摘录与代码示例隔离

一致性审查识别 Markdown 围栏代码块，包括三个及以上反引号或波浪线组成的开始/结束标志。结束标志必须与起始标志字符一致，且长度不少于起始围栏；代码示例中的工期数字不当作当前投标人正式承诺。

单行 Markdown 正文很长时，审查报告中的 excerpt 会以实际命中的工期、服务期限、质保期或响应时限所在位置为中心截取，不再固定提供最前 180 字而遗漏冲突。审查仍仅执行保守模式识别，不代表自动核实所有合同语义。

