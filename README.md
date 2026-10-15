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
