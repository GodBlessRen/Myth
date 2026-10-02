/* UI owns presentation only. Durable control and completion belong to Runtime. */
"use strict";
const $ = id => document.getElementById(id);
const state = {selected:null, status:null, busy:false, generation:0, notesKey:"", runsKey:"", deliveryKey:"", inspectorKey:"", pending:null, timer:null};
const labels = {RUNNING:"执行中", SUCCEEDED:"已核验完成", WAITING_USER:"等待答复", UNKNOWN:"结果待核对", FAILED:"已停止 · 失败", CANCELLED:"已停止", BUDGET_EXHAUSTED:"步数或额度已用完"};
const meterLabels = {model_calls:"决策次数", tool_calls:"工具调用", input_tokens:"输入 Token", output_tokens:"输出 Token", read_bytes:"读取字节", write_bytes:"写入字节"};
const providerLabels = {scripted:"本地演示",ollama:"Ollama",openai:"OpenAI", "pi-openai":"Pi OAuth"};
const money = n => Number(n || 0).toLocaleString("zh-CN");
function node(tag, cls, text) { const n=document.createElement(tag); if(cls)n.className=cls; if(text!==undefined)n.textContent=String(text); return n; }
function show(id, yes) { $(id).classList.toggle("hidden", !yes); }
function toast(message) { $("toast").textContent=message; show("toast",true); clearTimeout(toast.timer); toast.timer=setTimeout(()=>show("toast",false),5500); }
async function api(path, body) {
  const controller=new AbortController(); const timer=setTimeout(()=>controller.abort(),35000);
  try { const r=await fetch(path,{method:body===undefined?"GET":"POST",headers:{"Content-Type":"application/json"},body:body===undefined?undefined:JSON.stringify(body),signal:controller.signal});
    const data=await r.json(); if(!r.ok)throw new Error(data.error || `HTTP ${r.status}`); return data;
  } finally { clearTimeout(timer); }
}
function files() { return $("files").value.split(/\r?\n/).map(x=>x.trim()).filter(Boolean); }
function fileOptions(select, selected) {
  select.replaceChildren(); const values=files();
  if(!values.length)select.append(node("option","","请先填写允许处理的文件"));
  values.forEach(path=>{ const opt=node("option","",path); opt.value=path; select.append(opt); });
  if(values.includes(selected))select.value=selected;
}
function addRule(data={}) {
  const wrap=node("div","rule"); const meta=node("div","rule-meta");
  const select=node("select"); select.className="rule-path"; select.setAttribute("aria-label","规则对应文件"); fileOptions(select,data.path);
  const remove=node("button","remove-rule","×"); remove.setAttribute("aria-label","删除这条规则");
  remove.onclick=()=>{if($("rules").children.length>1)wrap.remove();else toast("至少保留一条完成标准。");};
  meta.append(select,remove); const grid=node("div","rule-fields");
  for(const [key,title,value] of [["old_text","原文字",data.old_text??"foo"],["new_text","替换为",data.new_text??"bar"],["expected_count","次数",data.expected_count??1]]) {
    if(key==="new_text")grid.append(node("div","rule-arrow","→"));
    const field=node("div","field"); const input=node(key==="expected_count"?"input":"textarea");
    input.id=`rule-${crypto.randomUUID()}`; input.dataset.field=key; input.value=value;
    if(key==="expected_count"){input.type="number";input.min="1";input.step="1";}else {input.rows=2;input.spellcheck=false;}
    const label=node("label","",title);label.htmlFor=input.id;field.append(label,input);grid.append(field);
  }
  wrap.append(meta,grid);$("rules").append(wrap);
}
function rules() {
  return [...$("rules").children].map(wrap=>{const value={path:wrap.querySelector("select").value};
    wrap.querySelectorAll("[data-field]").forEach(input=>value[input.dataset.field]=input.dataset.field==="expected_count"?Number(input.value):input.value);
    if(!files().includes(value.path)||!value.old_text||!Number.isInteger(value.expected_count)||value.expected_count<1)throw new Error("每条规则都需要文件、非空原文字和正整数次数。");return value;});
}
function providerPayload(){return {provider:$("provider").value,model:$("model").value.trim(),ollama_url:$("ollamaUrl").value.trim(),pi_command:"pi"};}
function updateConfig(){
  $("configSummary").textContent=`${$("provider").selectedOptions[0].textContent.split(" · ")[0]} · 最多 ${$("maxSteps").value} 步`;
  localStorage.setItem("myth-settings",JSON.stringify(providerPayload()));
}
async function checkProvider(){
  $("checkProvider").disabled=true;$("providerState").textContent="检查连接…";
  try {const p=providerPayload();const r=await api("/api/provider/check",p);$("providerState").className="provider-pill "+(r.ready?"good":"bad");
    $("providerState").textContent=r.ready?(p.provider==="scripted"?"本地演示":"连接已就绪"):"连接未就绪";
    $("providerDetail").textContent=r.ready?(p.provider==="scripted"?"固定规则演示，不调用模型。":"已通过基础连接检查，实际调用仍需验证。"):r.details?.error||"检查模型或登录状态。";
    $("modelOptions").replaceChildren();(r.details?.models||[]).forEach(model=>{const o=node("option");o.value=model;$("modelOptions").append(o);});
    if(!$("model").value&&(r.details?.models||[])[0])$("model").value=r.details.models[0];updateConfig();
  }catch(e){$("providerState").textContent="连接检查失败";toast(e.message);}finally{$("checkProvider").disabled=false;}
}
function setBusy(value){state.busy=value;["start","demo"].forEach(id=>$(id).disabled=value);}
function address(id){const url=new URL(location.href);if(id)url.searchParams.set("run",id);else url.searchParams.delete("run");history.replaceState(null,"",url);}
function newRun(){state.selected=null;state.status=null;state.notesKey="";state.generation++;address(null);show("emptyState",true);show("taskForm",true);show("runView",false);$("runKicker").textContent="新任务";$("providerState").textContent=providerLabels[$("provider").value];$("providerState").className="provider-pill";renderInspector(null);refreshRuns();}
async function selectRun(id){const generation=++state.generation;state.selected=id;state.notesKey="";address(id);
  try{const r=await api(`/api/runs/${encodeURIComponent(id)}`);if(generation===state.generation)renderStatus(r);refreshRuns();}catch(e){toast(e.message);}}
async function startRun(){
  if(state.busy)return;
  try{const allowed=files();if(!allowed.length)throw new Error("先填写至少一个允许处理的文件，或点击上方体验演示。");
    const acceptance=rules();const p=providerPayload();if(!p.model)throw new Error("在模型与运行设置中填写模型名称。");
    const payload={...p,goal:$("goal").value.trim()||`按 ${acceptance.length} 条固定规则替换文字，保留其他内容。`,files:allowed,acceptance,
      max_steps:Number($("maxSteps").value),max_output_tokens:Number($("maxTokens").value),thinking:$("thinking").value||null};
    const fingerprint=JSON.stringify(payload);if(state.pending?.fingerprint!==fingerprint)state.pending={fingerprint,request_id:crypto.randomUUID()};
    setBusy(true);const r=await api("/api/runs",{...payload,request_id:state.pending.request_id});state.pending=null;await selectRun(r.run_id);
  }catch(e){toast(e.message);}finally{setBusy(false);}
}
async function demo(){if(state.busy)return;setBusy(true);try{const r=await api("/api/demo",{});await selectRun(r.run_id);}catch(e){toast(e.message);}finally{setBusy(false);}}
async function control(action){const id=state.selected;if(!id)return;$(action==="cancel"?"cancelRun":"continueRun").disabled=true;
  try{await api(`/api/runs/${encodeURIComponent(id)}/${action}`,{});if(state.selected===id)await selectRun(id);}catch(e){toast(e.message);}finally{$("cancelRun").disabled=false;$("continueRun").disabled=false;}}
async function answer(event){event.preventDefault();const id=state.selected;const question=state.status?.agent?.question_id;const text=$("prompt").value.trim();if(!text||!question)return;
  $("send").disabled=true;try{await api(`/api/runs/${encodeURIComponent(id)}/resume`,{text,question_id:question});$("prompt").value="";if(state.selected===id)await selectRun(id);}catch(e){toast(e.message);}finally{$("send").disabled=false;}}
async function refreshRuns(){
  try{const r=await api("/api/runs");const signature=JSON.stringify([r.runs,state.selected]);if(signature===state.runsKey)return;state.runsKey=signature;
    $("runCount").textContent=String(r.runs.length).padStart(2,"0");$("runList").replaceChildren();
    if(!r.runs.length)$("runList").append(node("p","quiet","还没有任务。"));
    r.runs.forEach(run=>{const b=node("button","run-item"+(run.run_id===state.selected?" active":""));b.append(node("strong","",run.goal));
      const meta=node("small");meta.append(node("span","",labels[run.status]||run.status),node("span","",run.run_id.slice(4,10)));b.append(meta);b.onclick=()=>selectRun(run.run_id);$("runList").append(b);});
  }catch(e){console.warn("run list",e.message);}
}
function renderTimeline(notes){
  const signature=JSON.stringify(notes);if(signature===state.notesKey)return;state.notesKey=signature;
  const expanded=new Set([...$("timeline").querySelectorAll("details[open]")].map(d=>d.dataset.sequence));$("timeline").replaceChildren();
  const titles={goal:"任务目标",decision:"下一步决定",tool_result:"执行结果",tool_rejected:"步骤被拒绝",verification_rejected:"核验未通过",question:"需要你的答复",user:"你的答复",final:"核验完成"};
  notes.forEach(note=>{const p=note.payload;const entry=node("article",`entry ${note.kind}`);const head=node("div","entry-head");
    let title=titles[note.kind]||note.kind;if(note.kind==="tool_result")title=p.capability_id==="file.read"?"已读取受管文件":"已完成精确替换";
    head.append(node("span","",title),node("span","entry-seq",String(note.sequence).padStart(2,"0")));entry.append(head);
    let body=p.text||p.error||p.reason||"";
    if(note.kind==="decision")body=p.decision_type==="tool_call"?`${p.capability_id==="file.read"?"读取文件":"执行替换"} · ${p.reason}`:p.decision_type==="ask_user"?p.question:p.claim;
    if(note.kind==="tool_result")body=p.source_file.split(/[\\/]/).at(-1)+(p.has_more?` · 已读至第 ${p.next_offset} 字符，后续内容可分页读取。`:"");
    entry.append(node("div","entry-body",body));if(p.preview!==undefined)entry.append(node("pre","entry-preview",p.preview));
    if(p.evidence_ref||p.snapshot_ref){const details=node("details");details.dataset.sequence=String(note.sequence);details.open=expanded.has(String(note.sequence));details.append(node("summary","","查看依据"),node("p","",p.evidence_ref||p.snapshot_ref));entry.append(details);}
    $("timeline").append(entry);
  });
}
function renderDelivery(data){const signature=JSON.stringify([data.run.run_id,data.delivery,data.acceptance.files]);if(signature===state.deliveryKey)return;state.deliveryKey=signature;
  $("delivery").replaceChildren();show("delivery",!!data.delivery);if(!data.delivery)return;
  $("delivery").append(node("h2","","结果已核验，可以交付。"),node("p","",data.delivery.final_text));
  data.acceptance.files.forEach((file,index)=>{const a=node("a","artifact-link");a.href=`/api/runs/${encodeURIComponent(data.run.run_id)}/artifacts/${index}`;a.download=file.path.split(/[\\/]/).at(-1);
    a.append(node("span","",a.download),node("span","","下载副本 ↓"));$("delivery").append(a);});
}
function renderInspector(data){
  const signature=data?JSON.stringify([data.agent.provider_id,data.acceptance,data.model.budgets,data.verification,data.model.events]):"empty";
  if(signature===state.inspectorKey)return;state.inspectorKey=signature;
  ["budgets","acceptance","facts","events"].forEach(id=>$(id).replaceChildren());
  if(!data){$("acceptance").textContent="提交时固定文件和替换规则。";$("budgets").textContent="运行后显示实际用量。";$("facts").textContent="核对完整内容后才会交付。";$("events").textContent="还没有执行事件。";$("eventCount").textContent="00";return;}
  const manifest=data.acceptance;
  manifest.rules.forEach((rule,i)=>{const f=node("div","fact");f.append(node("b","",`${String(i+1).padStart(2,"0")} · ${rule.path.split(/[\\/]/).at(-1)}`),node("small","",`${JSON.stringify(rule.old_text)} → ${JSON.stringify(rule.new_text)} · ${rule.expected_count} 次`));$("acceptance").append(f);});
  if(!manifest.rules.length)$("acceptance").textContent="此任务没有固定目标验收合同，无法核验交付。";
  (data.model.budgets||[]).forEach(row=>{if(data.agent.provider_id==="scripted"&&row.meter.includes("tokens"))return;
    const b=node("div","budget-row");const line=node("div","budget-line");line.append(node("span","",meterLabels[row.meter]||row.meter),node("span","",`${money(row.settled)} / ${money(row.limit_units)}`));b.append(line);
    const track=node("div","budget-track");let available=100;for(const [key,cls]of [["settled","budget-fill"],["reserved","budget-reserved"],["unknown_held","budget-unknown"]]){const segment=node("div",cls);const percentage=Math.max(0,Math.min(available,Number(row[key])/Math.max(1,row.limit_units)*100));segment.style.width=percentage+"%";available-=percentage;track.append(segment);}b.append(track);
    if(row.reserved||row.unknown_held)b.append(node("small","",`预留 ${money(row.reserved)} · 待核对 ${money(row.unknown_held)}`));$("budgets").append(b);});
  const report=data.verification.at(-1);if(report){const f=node("div","fact");f.append(node("b","",report.verdict==="PASS"?"完整内容与固定目标一致":report.verdict==="FAIL"?"结果与完成标准不一致":"证据尚不充分"),node("small","",report.reason),node("small","",report.report_id));$("facts").append(f);}else $("facts").textContent="尚未进入完成核验。";
  const events=data.model.events||[];$("eventCount").textContent=String(events.length).padStart(2,"0");[...events].reverse().slice(0,30).forEach(ev=>{const e=node("div","event");e.append(node("span","n",String(ev.sequence).padStart(2,"0")));const c=node("div");c.append(node("strong","",ev.kind),node("small","",JSON.stringify(ev.payload)));e.append(c);$("events").append(e);});
}
function renderStatus(data){
  state.status=data;const a=data.agent;const interrupted=a.status==="RUNNING"&&!data.driver_active;show("emptyState",false);show("taskForm",false);show("runView",true);
  $("providerState").textContent=providerLabels[a.provider_id]||a.provider_id;$("providerState").className="provider-pill";
  $("runTitle").textContent=data.run.goal;$("runKicker").textContent=a.provider_id==="scripted"?"固定规则演示":"Agent 任务";
  $("stateBadge").textContent=labels[a.status]||a.status;$("stateBadge").className=`state-badge ${a.status.toLowerCase()}`;$("stepCount").textContent=`${a.current_step} / ${a.max_steps} STEPS`;
  [...$("progress").children].forEach((n,i)=>n.classList.toggle("active",i===0||i===1&&a.current_step>0||i===2&&!!data.delivery));
  const notice=a.status==="UNKNOWN"?`结果仍待核对，系统不会盲目重做。\n${a.error||""}`:interrupted?"执行已中断。可核对持久记录后继续。":a.error||"";
  $("runNotice").textContent=notice;show("runNotice",!!notice);show("continueRun",a.status==="UNKNOWN"||interrupted);show("cancelRun",["RUNNING","UNKNOWN","WAITING_USER"].includes(a.status));
  show("answerForm",a.status==="WAITING_USER");$("waitingBanner").textContent=a.pending_question||"";
  renderTimeline(data.notes);renderDelivery(data);renderInspector(data);
}
async function poll(){clearTimeout(state.timer);await refreshRuns();const id=state.selected;const generation=state.generation;
  if(id){try{const r=await api(`/api/runs/${encodeURIComponent(id)}`);if(id===state.selected&&generation===state.generation)renderStatus(r);}catch(e){console.warn("run status",e.message);}}
  state.timer=setTimeout(poll,document.hidden?6000:state.status?.driver_active?750:2500);
}
$("newRun").onclick=newRun;$("start").onclick=startRun;$("demo").onclick=demo;$("addRule").onclick=()=>addRule();
$("files").oninput=()=>document.querySelectorAll(".rule-path").forEach(s=>fileOptions(s,s.value));
$("answerForm").onsubmit=answer;$("cancelRun").onclick=()=>control("cancel");$("continueRun").onclick=()=>control("continue");
$("checkProvider").onclick=checkProvider;$("provider").onchange=()=>{$("model").value=$("provider").value==="scripted"?"exact-patch-demo":"";$("providerState").textContent=$("provider").value==="scripted"?"本地演示":"尚未检查";updateConfig();};
$("maxSteps").oninput=updateConfig;$("model").onchange=updateConfig;
$("historyToggle").onclick=()=>{const open=document.querySelector(".rail").classList.toggle("history-open");$("historyToggle").setAttribute("aria-expanded",String(open));};
$("evidenceToggle").onclick=()=>{const open=$("inspector").classList.toggle("open");$("evidenceToggle").setAttribute("aria-expanded",String(open));};
function closeEvidence(){$("inspector").classList.remove("open");$("evidenceToggle").setAttribute("aria-expanded","false");$("evidenceToggle").focus();}
$("closeEvidence").onclick=closeEvidence;
document.addEventListener("keydown",e=>{if(e.key==="Escape"&&$("inspector").classList.contains("open"))closeEvidence();});
try{const saved=JSON.parse(localStorage.getItem("myth-settings"));if(saved&&["scripted","ollama","openai","pi-openai"].includes(saved.provider)){$("provider").value=saved.provider;$("model").value=saved.model||"";$("ollamaUrl").value=saved.ollama_url||"http://127.0.0.1:11434";}}catch{}
addRule();updateConfig();const initial=new URL(location.href).searchParams.get("run");if(initial)selectRun(initial);poll();
