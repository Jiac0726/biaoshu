# biaoshu V1 发布候选：集成验收与发布门槛

> 本文是**发布候选（RC）**的技术验收说明，不是正式投标合规证明、真实模型质量验收或 GitHub 独立代码审查批准。未得到独立 reviewer 的 `APPROVED` 和用户明确的主分支合并授权前，不合并 `main`。

## 已完成的可复核工程交付

- 候选基线：PR #22 HEAD `afdacb03d14519c63db3f60c3272410ac39fd572`，其祖先涵盖堆叠 PR #1—#21。
- 最新合成测试基线：GitHub Actions `38743306412`，Python 3.10/3.12 **各 272 tests PASS**；`38743306388` 集成验收 **各 3/3**，包含 **7 项合成 E2E**。
- 本仓库的历史行级自动审查意见在当次核对时已逐条补修复与回归测试并消项，包括最新审批 journal 恢复时核对活动 PID 的风险。线程 resolved 不等于第三方独立 APPROVED。
- 实现范围：本地招标原文 TXT/DOCX/PDF 索引及来源校验、技术评分候选、模型辅助分析、人工确认、一级目录锁定、逐章生成与审批、恢复、跨章一致性、追溯和语义建议、可审核 Word 输出。
- 外发数据门禁：默认模型本地地址；远程传输须显式允许。不要把客户资料、密钥或真实商业文书提交公共 GitHub 仓库。

## Windows 本地验证命令（测试采用合成数据）

```powershell
git clone https://github.com/Jiac0726/biaoshu.git
cd biaoshu
git fetch origin release/v1-rc-complete-20261015
git switch --track origin/release/v1-rc-complete-20261015
py -m pip install -e ".[docs]"
py -m unittest discover -s tests -v
py scripts/validate_release_candidate.py
```

严格项目审核、正式导出等命令必须提供**当前原始招标文件及其索引**。示例：

```powershell
py -m biaoshu check ./workspaces/my-bid --output ./workspaces/my-bid/reports/check.json
py -m biaoshu audit ./workspaces/my-bid --index ./extracted/tender.index.json --source-dir ./sources --output ./workspaces/my-bid/reports/audit.json
py -m biaoshu export ./workspaces/my-bid --index ./extracted/tender.index.json --source-dir ./sources --output ./output/technical-bid.docx
```

## 正式启用之前必须完成（不得以模拟测试替代）

- [ ] **独立代码审查**：至少一名有权限、不同于代码提交者的 reviewer 给出 `APPROVED`，审核所有高危恢复路径和插件/模型网络边界。
- [ ] **GitHub 分支保护**：由仓库所有者批准并设置 `main` PR+CI 保护，禁止未经审查的直接推送。
- [ ] **真实本地模型验收**：在用户本机对模型 completion、长招标文件召回、分档评分、证据引用、章节事实约束和多轮审批实测；验证隐私与授权。
- [ ] **授权脱敏真实样本**：获得权利人许可后，在非公开受控环境核验至少代表性的 TXT/DOCX/PDF（含跨页复杂表格）并由审稿人签字确认。
- [ ] **Windows 文件系统恢复试验**：在可控沙箱中检查并发写入、程序被终止、断电/权限中断和恢复日志的真实行为；不得在真实投标原件上试验。
- [ ] **正式 Word 人工复核**：目录层次、响应完整性、引用来源、篇幅、页眉页脚、交付样式、评分点与资质要求逐项核对。
- [ ] **用户明确授权合并和发布**：将本 RC PR 合并到 `main` 前应由仓库所有者确认版本、审查意见与 CI，全链重新验证后再发布 tag。

## 不能宣称的事

当前全部自动化结果来自合成招标文字、模拟模型和 CI 环境；不能宣称实际本地模型准确率、真实评分覆盖率、招标文件法律合规或真实硬件崩溃安全。跨两个不同文件的提交是日志支持的可检测/可恢复流程，不是数据库 ACID 事务。

## 审查签署区（待填写）

| 验收事项 | 审查人/时间 | 结论 |
|---|---|---|
| 独立代码审查 | 待填写 | 未验收 |
| 模型与脱敏招标样本 | 待填写 | 未验收 |
| Windows 写入与恢复 | 待填写 | 未验收 |
| Word 正式投标适用性 | 待填写 | 未验收 |
| 主分支合并授权 | 待填写 | 未授权 |
