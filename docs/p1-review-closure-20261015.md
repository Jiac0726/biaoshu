# P1 代码审查消项依据（2026-10-15）

> 这是对当前累积候选分支的技术风险逐项复核。历史 PR 的原始基线代码仍可能包含问题；判断依据为 PR #13 + 本分支的累积代码和 CI。**消项不等于代码已合并 main、人工批准或招标业务验收。**

| 来源 PR | P1 风险 | 累积版本修复 / 回归验证 |
|---|---|---|
| #1 | 可伪造索引文本而保留真实原件 SHA | evidence.py 重新解析真实原件并逐块对比；test_integration_blockers.test_fake_block_with_real_file_digest_does_not_pass |
| #3 | localhost 模型请求被环境代理转发 | ai_tender_analysis.py 显式空 ProxyHandler；test_integration_blockers.test_model_adapter_ignores_proxy_environment |
| #6 | 删除检查点放行未审核 AI 草稿 | core.inspect 严格检查正文 AI 待审 banner；test_integration_blockers.test_missing_checkpoint_never_approves_banner_draft |
| #6 | 需求/事实/目录变更后批准旧草稿 | section_writer.py 绑定项目上下文 SHA，批准及严格审核持续复验；test_integration_blockers.test_changed_requirement_or_fact_blocks_approval；test_approved_chapter_detects_subsequent_fact_changes |
| #6 | 模型执行期间替换原件与索引却接受旧草稿 | section_writer.py 保存初始来源索引快照与原件 hash，返回后比较；test_integration_blockers.test_model_source_and_index_changed_together_is_blocked |
| #7 | 2 小时内、日期被误作等式 | consistency.py 排除上下限尾缀、日期与非精确值；test_integration_blockers.test_bounded_values_do_not_create_false_conflicts / test_calendar_date_not_parsed_as_year_duration |
| #7 | 供货子工期被误认整个项目工期 | consistency.py 拒绝前置中文复合标签的尾部命中；test_integration_blockers.test_subschedule_is_not_global_project_duration |
| #7 | verified 的不超过/不少于被强行作等式 | consistency._reference 只对完全匹配的数值单位建立等式基线；test_bounded_values_do_not_create_false_conflicts |
| #7 | 分钟或秒级响应承诺完全漏检 | _STATEMENT 与 _UNIT_NAMES 支持分钟、秒；test_integration_blockers.test_minute_level_conflicting_response_times_are_detected |
| #7 | 句内旧记录引述造成硬冲突 | 排除书面内嵌引述；test_integration_blockers.test_quoted_obsolete_duration_is_not_current_promise |
| #7 | 加粗 Markdown 让数值承诺绕过审查 | 在解析前去除简单加粗定界符；test_integration_blockers.test_bold_markdown_cannot_hide_conflicting_durations |
| #7 | 有效但泛化的 duration/period 事实键被忽略 | **本次新增**：无 category 的已核实期限返回 ambiguous_verified_duration 阻断；指定 service_duration 等类别后建立基线并核对。test_consistency 中新增 5 项 |

## 通用期限事实的规范化

对具有通用键名的 verified 事实（duration、period、期限、时长），需要显式写明 `category`，其值仅可为：`project_duration`、`service_duration`、`warranty_duration`、`response_time`。不填或填入其他值，严格审核阻断；不会无依据猜测是项目工期还是服务期限。

示例：

```json
{
  "facts": [{
    "key": "duration",
    "category": "service_duration",
    "value": "30日",
    "status": "verified",
    "evidence": {"file": "tender.txt", "location": "第3行", "quote": "服务期限30日"}
  }]
}
```

明确的 `30日` 与章节 `服务期限为45日` 会触发 `verified_fact_mismatch`；`不超过30日` 是上界而非等式，不会被强行套用该比较。此审查不能完成复杂约束的语义证明；必须结合来源招标文件人工审核。

## 准备主分支合并之前仍需要

1. 核实最新 PR #14 对应 GitHub CI 与该审查矩阵，确认历史 12 条 P1 均有后续分支覆盖；仅把有明确证据的审查线程标记已解决。
2. 保留现存未解决的 P2 问题，优先人工检查输出路径保护、输入编辑并发、AI 结束原因与高风险评分表语义。
3. 通过独立代码审查并按仓库所有者授权设置主分支保护；不能把行级 review thread 消项当成 GitHub APPROVED。
4. 对已授权脱敏的真实招标文件开展模型、PDF/DOCX 解析与 Word 质量验收。

## 后续 P2 安全边界说明

新 PR #15 聚焦模型 HTTP 完成状态和审稿文件独占保存。旧版只读取 `message.content`，即使返回 `finish_reason=length` 仍可能把局部有效 JSON 当完整审核建议。新版本在共用 `_request_model` 的传输层仅接受明确完成，避免生成中断状态向下游渗透。此外，在模型请求前检查目标报告与正式文件冲突，在实际写盘时再次以原子独占创建保护；所有模拟模型检查并不等于已完成真实本地模型验收。

