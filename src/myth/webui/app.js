const $ = (s) => document.querySelector(s);
const els = {
  runList: $("#runList"), newRun: $("#newRun"), runTitle: $("#runTitle"), runKicker: $("#runKicker"),
  config: $("#configPanel"), toggleConfig: $("#toggleConfig"), provider: $("#provider"), model: $("#model"),
  files: $("#files"), maxSteps: $("#maxSteps"), maxTokens: $("#maxTokens"), thinking: $("#thinking"),
  ollamaUrl: $("#ollamaUrl"), checkProvider: $("#checkProvider"), providerState: $("#providerState"),
  providerDetail: $("#providerDetail"), prompt: $("#prompt"), send: $("#send"), timeline: $("#timeline"),
  empty: $("#emptyState"), budgets: $("#budgets"), facts: $("#facts"), events: $("#events"),
  stateBadge: $("#stateBadge"), waitingBanner: $("#waitingBanner"), modeHint: $("#modeHint"), toast: $("#toast")
};

const state = { selected: null, runs: [], status: null, busy: false, timer: null };

function toast(msg) {
  els.toast.textContent = msg;
  els.toast.classList.remove("hidden");
  clearTimeout(toast.t);
  toast.t = setTimeout(() => els.toast.classList.add("hidden"), 2600);
}

function configPayload(extra={}) {
  return {
    provider: els.provider.value,
    model: els.model.value.trim(),
    ollama_url: els.ollamaUrl.value.trim(),
    pi_command: "pi",
    ...extra
  };
}

async function api(path, options={}) {
  const res = await fetch(path, {
    headers: {"Content-Type":"application/json"},
    ...options
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function statusClass(v) {
  return String(v || "").toLowerCase().replace(/[^a-z_]/g,"");
}

function shorten(v, n=30) {
  const s = String(v ?? "");
  return s.length > n ? s.slice(0,n-1) + "…" : s;
}

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function renderRuns() {
  els.runList.textContent = "";
  state.runs.forEach(run => {
    const b = el("button", "run-item" + (run.run_id === state.selected ? " active" : ""));
    const title = el("strong", "", run.goal || run.run_id);
    const meta = el("small");
    meta.append(el("span","", shorten(run.status,14)), el("span","", run.run_id.slice(4,10)));
    b.append(title, meta);
    b.onclick = () => selectRun(run.run_id);
    els.runList.append(b);
  });
}

async function refreshRuns() {
  try {
    const data = await api("/api/runs");
    state.runs = data.runs || [];
    renderRuns();
  } catch (e) { console.warn(e); }
}

function renderBudget(rows=[]) {
  els.budgets.textContent = "";
  if (!rows.length) { els.budgets.className="budgets empty-mini"; els.budgets.textContent="No budget data."; return; }
  els.budgets.className="budgets";
  rows.forEach(r => {
    const box=el("div","budget-row");
    const line=el("div","budget-line");
    line.append(el("b","",r.meter), el("span","",`${r.settled} / ${r.limit_units}`));
    const track=el("div","budget-track");
    const fill=el("div","budget-fill");
    const used=Math.min(100,(Number(r.settled||0)/Math.max(1,Number(r.limit_units||1)))*100);
    fill.style.width=used+"%";
    track.append(fill);
    if (r.unknown_held) {
      const unknown=el("div","budget-unknown");
      unknown.style.width=Math.min(100,(Number(r.unknown_held)/Math.max(1,Number(r.limit_units)))*100)+"%";
      track.append(unknown);
    }
    box.append(line,track);
    els.budgets.append(box);
  });
}

function noteText(note) {
  const p = note.payload || {};
  switch(note.kind) {
    case "goal": return p.text || "";
    case "decision":
      if (p.decision_type === "tool_call") return `TOOL_CALL → ${p.capability_id}\n${p.reason || ""}`;
      if (p.decision_type === "ask_user") return `ASK_USER\n${p.question || p.reason || ""}`;
      return `REQUEST_COMPLETION\n${p.claim || ""}\n${p.reason || ""}`;
    case "tool_result": return `Executed ${p.capability_id}\n${p.source_file || ""} → managed artifact`;
    case "tool_rejected": return p.error || "Tool proposal rejected";
    case "verification_rejected": return `Completion rejected\n${p.reason || ""}`;
    case "question": return p.text || "";
    case "user": return p.text || "";
    case "final": return p.text || "";
    default: return JSON.stringify(p,null,2);
  }
}

function renderTimeline(notes=[]) {
  els.timeline.textContent="";
  notes.forEach(note => {
    const wrap=el("article",`entry ${note.kind}`);
    const head=el("div","entry-head");
    head.append(el("span","entry-label",note.kind.replaceAll("_"," ")),el("span","entry-seq",String(note.sequence).padStart(2,"0")));
    const body=el("div","entry-body",noteText(note));
    wrap.append(head,body);
    const p=note.payload||{};
    if (note.kind==="tool_result") {
      const strip=el("div","evidence-strip");
      [["ACTION",p.action_id],["DIGEST",shorten(p.after_digest,24)],["RECEIPT",shorten(p.evidence_ref,70)]].forEach(([k,v])=>{
        strip.append(el("b","",k),el("span","",v||"—"));
      });
      wrap.append(strip);
    }
    els.timeline.append(wrap);
  });
  requestAnimationFrame(()=>els.timeline.scrollTop=els.timeline.scrollHeight);
}

function renderFacts(data) {
  els.facts.textContent="";
  const tool=(data.tool_actions||[]).at(-1);
  const model=(data.model?.model_invocations||[]).at(-1);
  const verify=(data.verification||[]).at(-1);
  const facts=[];
  if(model) facts.push(["MODEL TICKET",model.ticket_id || "—",model.state]);
  if(tool) facts.push(["TOOL RECEIPT",tool.evidence_ref || "—",tool.outcome || tool.attempt_state]);
  if(verify) facts.push(["VERIFICATION",verify.report_id,verify.verdict]);
  if(data.delivery) facts.push(["DELIVERY",data.delivery.delivery_id,"SUCCEEDED"]);
  if(!facts.length){els.facts.className="facts empty-mini";els.facts.textContent="No durable facts yet.";return}
  els.facts.className="facts";
  facts.forEach(([name,value,status])=>{
    const f=el("div","fact");
    f.append(el("strong","",`${name} · ${status||""}`),el("span","",value));
    els.facts.append(f);
  });
}

function renderEvents(events=[]) {
  els.events.textContent="";
  if(!events.length){els.events.className="events empty-mini";els.events.textContent="No events yet.";return}
  els.events.className="events";
  [...events].reverse().slice(0,40).forEach(ev=>{
    const row=el("div","event");
    row.append(el("span","n",String(ev.sequence).padStart(2,"0")));
    const copy=el("div");
    copy.append(el("strong","",ev.kind),el("small","",shorten(JSON.stringify(ev.payload||{}),110)));
    row.append(copy);
    els.events.append(row);
  });
}

function renderStatus(data) {
  state.status=data;
  const a=data.agent||{};
  const run=data.run||{};
  els.empty.classList.add("hidden");
  els.timeline.classList.remove("hidden");
  els.runTitle.textContent=run.goal || "Agent Run";
  els.runKicker.textContent=`${a.provider_id || "AGENT"} / ${a.model_id || ""}`;
  els.stateBadge.textContent=a.status || run.state || "UNKNOWN";
  els.stateBadge.className=`state-badge ${statusClass(a.status || run.state)}`;
  renderTimeline(data.notes||[]);
  renderBudget(data.model?.budgets || []);
  renderFacts(data);
  renderEvents(data.model?.events || []);
  const waiting=a.status==="WAITING_USER";
  els.waitingBanner.classList.toggle("hidden",!waiting);
  els.waitingBanner.textContent=waiting ? (a.pending_question || "Agent 正在等待你的输入") : "";
  els.modeHint.textContent=waiting ? "回答 Agent 的问题并继续" : "Enter 运行 · Shift+Enter 换行";
  els.prompt.placeholder=waiting ? "回复 Agent…" : "给 Myth 一个明确、可验证的任务…";
  els.send.disabled=["SUCCEEDED","BUDGET_EXHAUSTED","UNKNOWN","FAILED"].includes(a.status);
}

async function selectRun(id) {
  state.selected=id;
  renderRuns();
  try { renderStatus(await api(`/api/runs/${encodeURIComponent(id)}`)); }
  catch(e){toast(e.message)}
}

async function poll() {
  clearTimeout(state.timer);
  await refreshRuns();
  if(state.selected){
    try{
      const data=await api(`/api/runs/${encodeURIComponent(state.selected)}`);
      renderStatus(data);
    }catch(e){console.warn(e)}
  }
  const active=state.status?.agent?.status==="RUNNING";
  state.timer=setTimeout(poll,active?700:2200);
}

async function checkProvider() {
  els.providerState.className="provider-pill";
  els.providerState.innerHTML="<span></span> checking";
  try{
    const data=await api("/api/provider/check",{method:"POST",body:JSON.stringify(configPayload())});
    els.providerState.className="provider-pill "+(data.ready?"good":"bad");
    els.providerState.innerHTML=`<span></span> ${data.ready?"ready":"not ready"}`;
    const models=data.details?.models;
    els.providerDetail.textContent=Array.isArray(models)&&models.length ? `${models.length} local models` : (data.auth_type||"");
    if(data.ready && !els.model.value.trim() && Array.isArray(models) && models[0]) els.model.value=models[0];
    if(!data.ready) toast(data.details?.error || "Provider not ready");
  }catch(e){
    els.providerState.className="provider-pill bad";
    els.providerState.innerHTML="<span></span> error";
    toast(e.message);
  }
}

async function submit() {
  if(state.busy) return;
  const text=els.prompt.value.trim();
  if(!text) return;
  state.busy=true; els.send.disabled=true;
  try{
    const waiting=state.status?.agent?.status==="WAITING_USER" && state.selected;
    if(waiting){
      await api(`/api/runs/${encodeURIComponent(state.selected)}/resume`,{
        method:"POST",body:JSON.stringify(configPayload({text}))
      });
    }else{
      const files=els.files.value.split(/\r?\n/).map(v=>v.trim()).filter(Boolean);
      const data=await api("/api/runs",{
        method:"POST",
        body:JSON.stringify(configPayload({
          goal:text, files,
          max_steps:Number(els.maxSteps.value||6),
          max_output_tokens:Number(els.maxTokens.value||1024),
          thinking:els.thinking.value||null
        }))
      });
      state.selected=data.run_id;
      els.empty.classList.add("hidden");
      els.timeline.classList.remove("hidden");
    }
    els.prompt.value="";
    await poll();
  }catch(e){toast(e.message)}
  finally{state.busy=false;els.send.disabled=false}
}

function newRun() {
  state.selected=null;state.status=null;
  renderRuns();
  els.timeline.classList.add("hidden");
  els.empty.classList.remove("hidden");
  els.runKicker.textContent="NEW RUN";
  els.runTitle.textContent="把意图变成可验证的执行。";
  els.stateBadge.textContent="IDLE";
  els.stateBadge.className="state-badge";
  els.budgets.className="budgets empty-mini";els.budgets.textContent="No active run";
  els.facts.className="facts empty-mini";els.facts.textContent="Ticket / Receipt / Verification will appear here.";
  els.events.className="events empty-mini";els.events.textContent="No events yet.";
  els.waitingBanner.classList.add("hidden");
  els.prompt.placeholder="给 Myth 一个明确、可验证的任务…";
  els.prompt.focus();
}

els.toggleConfig.onclick=()=>els.config.classList.toggle("open");
els.checkProvider.onclick=checkProvider;
els.provider.onchange=checkProvider;
els.newRun.onclick=newRun;
els.send.onclick=submit;
els.prompt.addEventListener("keydown",e=>{
  if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();submit()}
});
els.prompt.addEventListener("input",()=>{
  els.prompt.style.height="auto";
  els.prompt.style.height=Math.min(160,els.prompt.scrollHeight)+"px";
});

refreshRuns().then(()=>{checkProvider();poll()});
