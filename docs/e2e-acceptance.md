# 脱敏端到端验收（合成数据）

本文件说明跨全部生产 CLI 命令的自动集成测试。示例源文件、模型返回和人工确认均为**测试专用虚构内容**，
没有真实招标文件、企业数据或 API 密钥，不会联系在线服务。

## 一键运行

```bash
python -m pip install -e '.[docs]'
python -m unittest tests.test_pipeline_e2e -v
# 若测试目录不是 package，可使用：
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
