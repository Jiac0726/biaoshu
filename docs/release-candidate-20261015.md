# 标书 Release Candidate 集成验收记录

版本日期：2026-10-15

## 范围

本验收分支 `release/rc-integration-validation-20261015` 建立在 PR #12 的已测试功能快照之上。该快照已包含 PR #1—#11 的累积代码，以及评分多档、一级目录直接叶标题锁和 AI 章节中断恢复的 PR #12 加固代码。**分支存在不意味着以上 PR 已合并 main。**

基线提交：`15a65727875f76b601518bb3fe045674c324c4b4`。本验收分支新增了可重复执行的离线验收脚本和 GitHub Actions 流程，不包含真实招标材料或云端 API 凭据。

## 验收方法

```powershell
python -m pip install -e ".[docs]"
python scripts/validate_release_candidate.py
# 如需本地留存记录（不可覆盖已有报告）：
python scripts/validate_release_candidate.py --report reports/rc-acceptance-local.json
```

同一验收入口连续运行：

1. 完整 unittest 发现与运行；
2. 以虚构招标文本、模拟 AI、模拟人工确认穿透所有 CLI 模块的 Word 文件生产测试；
3. `python -m biaoshu --help` CLI 启动测试。

新建的 `.github/workflows/integration-acceptance.yml` 在候选 PR 上分别使用 Python 3.10 与 3.12 运行上述入口；原有 `ci.yml` 继续运行单元测试。任何一项失败，本轮候选应标记为未通过。

## 安全要求

- 输入为虚构招标材料，模型请求由测试替身响应；本验收无需网络模型服务。
- 不创建真实投标成果，不主动提交个人/企业文件、密钥、业务报价。
- 此验收无法证明真实模型对评分规则的语义理解、资质/业绩真实性、否决条款遵守或 Word 高保真排版。
- 中断恢复脚本、分支保护和真实数据准入仍须人工审查。

## 阶段结论与剩余阻断

**工程验收**：以最新 CI 工作流结果为准，不得单纯因为创建验收分支而宣称成功。

**尚未具备发布授权**：
- PR #1—#12 仍未合并到 main；
- 未取得独立 APPROVED 代码审查；
- `main` 未开启强制审查及必需 CI 的分支保护；
- 真实本地模型兼容性与经授权脱敏招标文件业务验收仍未完成；
- 复杂评分、多文件断电持久化、真实 Windows 恢复流程需单独验证。

建议先审查 PR #12 与本分支 PR 的 CI，再进行独立 code review，之后由仓库所有者决定是否按顺序合并到受保护 main。


## 本轮集成复核新增结果

- PR #12 已修复多档评分未进入人工审核清单的高优先级遗漏、一级叶节点标题损坏的非结构化异常、AI 新建章节部分写入以及已批准内容被二次签署的问题。此类审核不能被单元测试通过所替代。
- PR #13 的离线验收报告现在使用 `open('x')` 独占创建，避免并发执行覆盖历史结果；同时记录**实际 checkout Git SHA**与已跟踪工作树是否干净，不能把文档中以前的基线提交误当作当前测试版本。若本地没有 Git，版本状态将明确标为 unverified。
- 最新 PR 验收仍须以 GitHub Actions 实际 checkout/最新 head SHA 为准。没有独立 Approved review、分支保护和真实授权脱敏案例验收前，不得称为正式发布。
