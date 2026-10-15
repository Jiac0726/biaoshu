"use strict";

let token = "";
let projectId = "";
let snapshot = null;
let working = false;
const $ = (id) => document.getElementById(id);
const esc = (value) => String(value == null ? "" : value).replace(/[&<>"']/g,
  (ch) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
const params = (entries) => new URLSearchParams(entries).toString();

function notify(message, failed) {
  const toast = $("toast");
  toast.textContent = String(message || "操作完成");
  toast.className = "visible" + (failed ? " error" : "");
}
function loading(show) {
  working = show;
  $("working").classList.toggle("hidden", !show);
}
async function request(path, opts) {
  const response = await fetch(path, opts || {});
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || ("HTTP " + response.status));
  return payload;
}
async function post(path, data) {
  return request(path, {
    method: "POST",
    headers: {"Content-Type":"application/json","X-Biaoshu-Token":token},
    body: JSON.stringify(data)
  });
}
function modelOptions() {
  return {model: $("modelName").value.trim(), endpoint: $("modelEndpoint").value.trim()};
}
async function bootstrap(selectId) {
  const info = await request("/api/bootstrap");
  token = info.token;
  const items = info.projects || [];
  if (selectId) projectId = selectId;
  if (projectId && !items.some((p) => p.id === projectId)) projectId = "";
  if (!projectId && items.length) projectId = items[0].id;
  $("projectList").innerHTML = items.length
    ? items.map((p) => '<button class="project-item' + (p.id === projectId ? " active" : "") +
        '" data-project="' + esc(p.id) + '"><span class="project-icon">▤</span><span class="project-title">' +
        esc(p.name) + "</span></button>").join("")
    : '<p class="hint">暂无项目，点击右上角 ＋ 创建。</p>';
  document.querySelectorAll("[data-project]").forEach((node) => node.addEventListener("click", async () => {
    if (working) return;
    projectId = node.dataset.project;
    await bootstrap(projectId);
  }));
  $("workspace").classList.toggle("hidden", !projectId);
  $("emptyState").classList.toggle("hidden", !!projectId);
  if (projectId) await refresh();
  else {
    $("projectTitle").textContent = "从招标文件到专业技术标";
    $("breadcrumb").textContent = "项目概览";
  }
}
async function createProject() {
  if (working) return;
  const name = prompt("请输入新的投标项目名称：", "新建技术标项目");
  if (!name) return;
  loading(true);
  try {
    const result = await post("/api/project", {name});
    await bootstrap(result.id);
    notify("已创建项目：" + result.name);
  } catch (err) {
    notify(err.message, true);
  } finally {
    loading(false);
  }
}
async function refresh() {
  if (!projectId) return;
  snapshot = await request("/api/project?" + params({id:projectId}));
  render();
}
function render() {
  const data = snapshot;
  const title = data.project.project_name || "未命名项目";
  $("projectTitle").textContent = title;
  $("breadcrumb").textContent = title;
  $("projectSubtitle").textContent = "导入资料 → 评分审核 → 规划目录 → AI 分章节写作 → 人工复核与 Word 导出";
  renderSources(data);
  renderSuggestions(data);
  renderReview(data);
  renderOutline(data);
  renderSections(data);
  renderTrace(data);
  renderAudit(data);
  renderDownloads(data);
}
function renderSources(data) {
  $("sourceCount").textContent = data.sources.length + " 份文件";
  $("sourceList").innerHTML = data.sources.length ? data.sources.map((f) =>
    '<div class="source-row"><div><div class="source-name">▧ ' + esc(f.name) + '</div>' +
    '<small class="candidate-sub">' + Math.ceil(f.bytes / 1024) + ' KB</small></div>' +
    (f.extracted ? '<span class="source-status">✓ 已生成证据索引</span>' :
     '<button class="secondary" data-extract="' + esc(f.name) + '">解析原件</button>') + "</div>"
  ).join("") : '<p class="hint">还没有上传招标资料。</p>';
  document.querySelectorAll("[data-extract]").forEach((node) => node.addEventListener("click",
    () => action("extract", {source:node.dataset.extract})));
}
function renderSuggestions(data) {
  const result = data.suggestions;
  if (!result) {
    $("suggestionList").innerHTML = '<p class="hint">尚无候选结果。先解析原始文件，再点击评分初筛或 AI 分析。</p>';
    return;
  }
  const items = result.candidates || [];
  const heading = '<div class="mini-heading">最近一次建议 · ' + esc(items.length) +
    " 项 · " + esc(data.report_selection.suggestions || "") + '</div>';
  $("suggestionList").innerHTML = heading + (items.length ? items.map((item) =>
    '<div class="suggestion-row"><div class="candidate-body">' +
    '<div class="candidate-title">' + esc(item.id || "") + ' · ' + esc(item.title || item.description || "待判断条款") + '</div>' +
    '<div class="candidate-sub">' + esc((item.evidence || {}).file || "") + " · " +
    esc((item.evidence || {}).location || "") + " · " +
    esc((item.evidence || {}).quote || "").slice(0,450) + "</div></div>" +
    '<span class="candidate-pill">' + (item.score == null ? "待核分值" : esc(item.score) + " 分") + "</span></div>"
  ).join("") : '<p class="hint">未找到候选。需要检查原文与提取警告，尤其是复杂评分表。</p>');
  const ambiguous = result.ambiguous_candidates || [];
  if (ambiguous.length) {
    $("suggestionList").innerHTML += '<p class="mini-heading">另有 ' + ambiguous.length +
      " 项多档或加减分规则，需要在审核清单单独处理。</p>";
  }
}
function option(value, current, label) {
  return '<option value="' + esc(value) + '"' + (current === value ? " selected" : "") + ">" + esc(label) + "</option>";
}
function renderReview(data) {
  const review = data.review;
  if (!review) {
    $("reviewArea").innerHTML = '<p class="hint">尚未创建审核清单。每条技术评分要求须有明确人工决定。</p>';
    return;
  }
  const suggestions = data.suggestions || {};
  const items = new Map((suggestions.candidates || []).map((c) => [c.id, c]));
  const rows = (review.decisions || []).map((entry) => {
    const item = items.get(entry.id) || {};
    return '<div class="review-row"><div><div class="candidate-title">' + esc(entry.id) +
      " · " + esc(item.title || item.description || "招标候选") + '</div><div class="candidate-sub">' +
      esc((item.evidence || {}).quote || "").slice(0,300) + '</div></div>' +
      '<select class="decision-select" data-rid="' + esc(entry.id) + '" aria-label="审核决策 ' + esc(entry.id) + '">' +
      option("pending",entry.decision,"待人工核对") +
      option("accept",entry.decision,"接受：登记技术响应") +
      option("reject",entry.decision,"拒绝：不登记") + "</select></div>";
  }).join("");
  const ambiguous = (review.ambiguous_decisions || []).map((entry) =>
    '<div class="review-row"><div><div class="candidate-title">' + esc(entry.id) +
    " · 多档评分／加减分规则</div><div class=\"candidate-sub\">不能直接将其中一个分值当成全部评分</div></div>" +
    '<select class="ambiguous-select" data-aid="' + esc(entry.id) + '">' +
    option("pending",entry.decision,"待复核") +
    option("not_applicable",entry.decision,"不登记（需理由）") +
    option("manually_registered",entry.decision,"已手动登记") +
    '</select><input class="ambiguous-reason review-reason" data-aid="' + esc(entry.id) +
    '" placeholder="人工判定理由" value="' + esc(entry.reason || "") + '"></div>'
  ).join("");
  $("reviewArea").innerHTML = '<div class="mini-heading">审核文件 · ' +
    esc(data.report_selection.review || "") + "</div>" +
    (rows || '<p class="hint">当前无确定性候选。</p>') +
    (ambiguous ? '<div class="mini-heading">多档评分专项复核</div>' + ambiguous : "") +
    '<label class="review-confirm"><input id="reviewConfirmed" type="checkbox"' +
    (review.acknowledgement ? " checked" : "") +
    '>我已逐项对照原始招标文件完成审核，确认所选接受项可登记为正式技术响应需求。未审查原件时请勿勾选。</label>';
}
function renderOutline(data) {
  $("sectionCount").textContent = (data.sections || []).length + " 章节";
  $("outlineEditor").classList.toggle("hidden", !data.outline_proposal);
  if (data.outline_proposal) {
    $("outlineRoots").value = JSON.stringify(data.outline_proposal.roots || [], null, 2);
  }
}
function renderSections(data) {
  const sections = data.sections || [];
  $("sectionsList").innerHTML = sections.length ? sections.map((sec) =>
    '<div class="chapter-row"><div class="chapter-top"><div class="chapter-left">' +
    '<div class="chapter-title">' + esc(sec.id) + " · " + esc(sec.title) +
    '<span class="status-badge ' + esc(sec.status) + '">' + esc(sec.status) + "</span></div>" +
    '<div class="chapter-sub">响应需求：' + esc((sec.requirement_ids || []).join(", ") || "未映射") + '</div></div>' +
    '<div class="chapter-controls"><button class="secondary" data-write="' + esc(sec.id) +
    '">生成本节</button><button class="primary" data-approve="' + esc(sec.id) +
    '">人工批准</button></div></div>' +
    (sec.body ? '<details><summary>查看章节正文</summary><div class="chapter-content">' +
    esc(sec.body) + "</div></details>" : "") + "</div>"
  ).join("") : '<p class="hint">先在人工审核阶段正式登记评分需求，再生成目录与章节。</p>';
  document.querySelectorAll("[data-write]").forEach((node) =>
    node.addEventListener("click", () => action("write", {section:node.dataset.write})));
  document.querySelectorAll("[data-approve]").forEach((node) =>
    node.addEventListener("click", () => action("approve", {section:node.dataset.approve})));
}
function renderTrace(data) {
  const trace=data.trace;
  if(!trace){$("traceArea").innerHTML='<p class="hint">尚未建立追溯台账。需要正式检查每项技术要求在正文的位置时，先点击“创建响应追溯台账”。</p>';return;}
  const rows=(trace.items||[]).map((item,i)=>
    '<div class="trace-row" data-trace-index="' + i + '"><div><strong>'+esc(item.requirement_id)+' → '+esc(item.section_id)+
    '</strong><span class="candidate-sub">请从上方章节正文中找到实际响应原句，并记录其在 .md 文件中的行号（从 1 起）</span></div>'+
    '<label>行号<input class="trace-line" type="number" min="1" value="'+esc(item.line==null?"":item.line)+'"></label>'+
    '<label>响应原句<input class="trace-quote" value="'+esc(item.quote||"")+'" placeholder="复制正文指定行的连续原句，至少12字"></label>'+
    '<label>审核决定<select class="trace-decision">'+
    option("pending",item.decision,"待审")+option("confirmed",item.decision,"人工确认")+
    '</select></label></div>'
  ).join("");
  $("traceArea").innerHTML='<div class="mini-heading">逐条响应段落位置（共 '+(trace.items||[]).length+' 项）</div>'+
    rows+'<label class="review-confirm"><input type="checkbox" id="traceConfirmed" '+
    (trace.acknowledgement?'checked':'')+'>我已经逐项比对招标评分要求和章节正文，确认以上段落位置确实为对应响应。不得由 AI 代为勾选。</label>';
}
async function saveTrace() {
  if(working||!snapshot||!snapshot.trace)return notify("请先创建追溯台账",true);
  const items=[];
  let error="";
  document.querySelectorAll(".trace-row").forEach((row)=>{
    const i=Number(row.dataset.traceIndex);
    const item=snapshot.trace.items[i];
    const value=row.querySelector(".trace-line").value.trim();
    const line=value===""?null:Number(value);
    if(value!==""&&(!Number.isInteger(line)||line<=0))error="响应行号必须是正整数";
    items.push({requirement_id:item.requirement_id,section_id:item.section_id,
      line:line,quote:row.querySelector(".trace-quote").value,
      decision:row.querySelector(".trace-decision").value});
  });
  if(error)return notify(error,true);
  loading(true);
  try{
    const result=await post("/api/action?"+params({id:projectId}),{
      action:"trace-save",items,confirmed:$("traceConfirmed")&&$("traceConfirmed").checked});
    await refresh();
    notify(result.message);
  }catch(err){notify(err.message,true);}
  finally{loading(false);}
}

function renderAudit(data) {
  const audit = data.audit;
  if (!audit) {
    $("auditArea").innerHTML = '<p class="hint">暂无严格审计报告。检查不通过时仍可导出明确标识的未完成草稿。</p>';
    return;
  }
  const issues = (audit.errors || []).slice(0,15);
  $("auditArea").innerHTML = '<div class="audit-status ' + (audit.ok ? "good" : "bad") +
    '"><strong>' + (audit.ok ? "✓ 机械检查通过" : "✕ 检查未通过") +
    '</strong><p>自动核验不能替代专业审稿；来源、评分内容及格式仍须人工复核。</p>' +
    (issues.length ? "<ul>" + issues.map((x) => "<li>" + esc(x) + "</li>").join("") + "</ul>" : "") +
    "</div>";
}
function renderDownloads(data) {
  const files = data.exports || [];
  $("exportList").innerHTML = files.length ? '<div class="mini-heading">已导出的 Word 文档</div>' +
    files.map((f) => '<div class="download-row">▤ ' + esc(f.name) +
      '<a href="/api/export?' + params({id:projectId,name:f.name}) +
      '">下载 DOCX ↗</a></div>').join("") : "";
}
async function uploadFiles() {
  if (working || !projectId) return;
  const files = Array.from($("fileUpload").files || []);
  if (!files.length) return notify("请先选择招标文件", true);
  loading(true);
  try {
    for (const file of files) {
      if (!/\.(pdf|docx|txt|md)$/i.test(file.name) || file.size > 40 * 1024 * 1024) {
        throw new Error("文件格式或大小不支持：" + file.name);
      }
      const url = "/api/upload?" + params({id:projectId,filename:file.name});
      await request(url, {method:"POST",headers:{"Content-Type":"application/octet-stream",
        "X-Biaoshu-Token":token},body:file});
    }
    $("fileUpload").value = "";
    await refresh();
    notify("上传成功。请点击各文件右侧的「解析原件」生成证据索引。");
  } catch (err) {notify(err.message, true);}
  finally {loading(false);}
}
async function saveReview() {
  if (working || !snapshot || !snapshot.review) return notify("请先创建审核清单", true);
  const decisions = {};
  document.querySelectorAll(".decision-select").forEach((el) => {decisions[el.dataset.rid] = el.value;});
  const ambiguous = {};
  document.querySelectorAll(".ambiguous-select").forEach((el) => {
    const id = el.dataset.aid;
    const reason = Array.from(document.querySelectorAll(".ambiguous-reason"))
      .find((node) => node.dataset.aid === id);
    ambiguous[id] = {decision:el.value,reason:reason ? reason.value : ""};
  });
  loading(true);
  try {
    const result = await post("/api/action?" + params({id:projectId}), {
      action:"review-save",decisions,ambiguous_decisions:ambiguous,
      confirmed:$("reviewConfirmed") && $("reviewConfirmed").checked
    });
    await refresh();
    notify(result.message);
  } catch (err) {notify(err.message,true);}
  finally {loading(false);}
}
async function saveOutline() {
  if (working || !snapshot || !snapshot.outline_proposal) return notify("先生成目录候选",true);
  let roots;
  try {roots=JSON.parse($("outlineRoots").value);}
  catch(err) {return notify("目录 JSON 格式错误：" + err.message,true);}
  loading(true);
  try {
    const result=await post("/api/action?" + params({id:projectId}),{action:"outline-save",roots});
    await refresh();
    notify(result.message);
  } catch(err){notify(err.message,true);}
  finally{loading(false);}
}
async function action(name, payload) {
  if (working || !projectId) return;
  const notes={
    "review-apply":"是否确认审核清单已保存、原始招标文件已逐项核对，并将接受项正式登记到项目？",
    "outline-apply":"确定应用目录候选？现有正文不会因此自动改写。",
    "outline-lock":"锁定一级目录的标题、顺序和章节归属后，后续修改将受到限制。确认锁定？",
    "approve":"你是否已经亲自阅读该章节，核对评分响应、事实与承诺，确定批准？",
    "final-export":"确认已经完成人工终审？程序会再次执行严格审核并阻止未满足条件的导出。"
  };
  if (notes[name] && !confirm(notes[name])) return;
  const input=Object.assign({action:name},payload || {});
  if (["analyze","write","semantic-review"].includes(name)) {
    Object.assign(input,modelOptions());
    if (!input.model) return notify("请先填写本机已安装模型的准确名称",true);
  }
  if (notes[name]) input.confirmed=true;
  if (name==="allocate") input.total=Number($("targetWords").value);
  loading(true);
  try {
    const result=await post("/api/action?" + params({id:projectId}),input);
    await refresh();
    if (result.download) {
      notify("Word 已导出：" + result.download + "。请从页面底部下载。");
    } else {
      notify(result.message || "操作完成", result.ok === false);
    }
  } catch(err) {notify(err.message,true);}
  finally{loading(false);}
}
document.addEventListener("DOMContentLoaded", () => {
  $("newProject").addEventListener("click",createProject);
  $("emptyCreate").addEventListener("click",createProject);
  $("uploadBtn").addEventListener("click",uploadFiles);
  $("reviewSave").addEventListener("click",saveReview);
  $("outlineSave").addEventListener("click",saveOutline);
  $("traceSave").addEventListener("click",saveTrace);
  document.querySelectorAll("[data-action]").forEach((node) =>
    node.addEventListener("click", () => action(node.dataset.action)));
  bootstrap().catch((err) => notify("本地服务连接失败：" + err.message,true));
});
