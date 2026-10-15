# 脱敏端到端验收（合成数据）

本文件说明跨全部生产 CLI 命令的自动集成测试。示例源文件、模型返回和人工确认均为**测试专用虚构内容**，
没有真实招标文件、企业数据或 API 密钥，不会联系在线服务。

## 一键运行

```bash
python -m pip install -e '.[docs]'
# tests 目录不是 Python package，使用 discover 指定测试文件：
python -m unittest discover -s tests -p 'test_pipeline_e2e.py' -v
python -m unittest discover -s tests -v
```

GitHub Actions 的常规 CI（Python 3.10、3.12）也将执行该测试文件。

## 覆盖的真实生产入口

测试通过 `biaoshu.cli.main()`，而非重新实现同等业务功能：

1. `init` 创建临时项目；`extract` 对虚构 TXT 建立带 SHA-256 的证据索引；`score-candidates` 产生规则建议。
2. `analyze-ai` 走真正的命令分发、文本块筛选、引文校验，但以 unittest.mock 代替**实际模型网络请求**。
3. `review-init` 默认全 pending；`review-import` 不允许未决策申请，预览不得落盘；
   决策与 acknowledgement 在测试夹具里模拟填写，**不能代表真实审稿人已审核**。
4. 生成一一对应需求、建立并锁定目录树、分配字数、建立章节脚手架。
5. `write-sections` 采用模拟模型逐节写作；检查未核实 facts 值不注入提示；
   `approve-section` 在测试环境模拟人工批准，严格审核须在批准前失败、批准后成功。
6. `consistency-audit` 读取实际 Markdown；`audit` 验证证据和核查结论；
   `export` 真正生成 Word，python-docx 重新打开并核对层级标题与正文。

## 故障回归

- 写作到第二章节时注入模拟网络中断，验证独立检查点与重试，第一节不被覆盖。
- 原招标 TXT 变化后必须阻断最终审计及非草稿 Word。
- 人工批准后正文被修改，并产生 30 日 / 45 日冲突时，一致性报告必须定位，
  严格审计和正式导出都不能成功。

## 不在测试证明范围内

该测试只证明已有 CLI 之间的结构、文件操作、审核状态和错误门禁在一组虚构数据中能协同工作。
**它不是对真实 LLM、评分语义理解、项目事实真实性、复杂 PDF/OCR、招标法律合规、高保真 Word 排版的验收。**
后续要以经过授权和脱敏的项目样本、真实本地模型、人工双人复核建立单独的验收基准；
不得把测试脚本中模拟的审核行为用于真实投标。


## 第22轮增强：四项独立可验证门禁

- `check` 现有端到端直接执行，核对成功项目的结构化 check 报告；跨章节 30/45 日冲突时，普通 `check` 返回成功但包含警告，正式 `audit` 和 `export` 明确阻断。
- 审核清单仍含 pending 时，测试会对 project、requirements、outline、facts 的**原始字节**在被拒绝的 `review-import --apply` 前后逐个核对，并检查未出现虚假事务日志或备份。
- 单独构建**不使用 AI 写作及审批 sidecar**的两节人工正文：先以 30/30 日通过正式审计，再改成 30/45 日，核对冲突编号和严格审计错误，并证实 DOCX 导出阻断不是由过期 AI 审批 hash 导致。
- 模拟写作按 S1/S2 写入两段不同的专属标记，重新读取真正导出的 DOCX，逐节检查标记只在其所属标题下出现一次，不会重复 S1 或遗漏 S2。

该覆盖只说明基于虚构文本及模拟模型的系统回归完整性；**不能代替真实 LLM 质量评估、脱敏真实招标样本和人工投标合规审批。**

