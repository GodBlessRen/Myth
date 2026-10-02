"use strict";

function inspectorStatus(status){
  const value=String(status||"IDLE").toUpperCase();
  if(["COMPLETED","SUCCEEDED"].includes(value))return [value,"success"];
  if(["RUNNING","WAITING_USER","RECOVERING","PAUSED"].includes(value))return [value,"running"];
  if(value==="UNKNOWN")return [value,"unknown"];
  if(["FAILED","CANCELLED","BUDGET_EXHAUSTED"].includes(value))return [value,"danger"];
  return [value,""];
}

function spineStep(label,detail,stateName,stateLabel){
  const row=el("div","spine-step "+(stateName||""));
  row.append(el("span","spine-node"));
  const copy=el("div","spine-copy");
  copy.append(el("strong","",label),el("small","",detail||""));
  row.append(copy,el("span","spine-state",stateLabel||""));
  return row;
}

function renderExecutionSpine(turn){
  const box=$("executionSpine");
  if(!box)return;
  box.replaceChildren();
  if(!turn){box.append(el("div","spine-empty","开始一个任务后，这里显示 Decision / Ticket / Result / Completion。"));return;}
  const latest=(turn.activities||[]).at(-1);
  const decision=latest?.decision;
  const operation=(turn.operations||[]).at(-1);
  const result=operation?.result||latest?.result;
  const hasDecision=!!decision;
  box.append(spineStep("Decision",hasDecision?(decision.decision_type==="tool_call"?decision.capability_id:decision.decision_type):("step "+(turn.current_step||0)+" / "+(turn.max_steps||0)),hasDecision?"done":turn.status==="RUNNING"?"active":"",hasDecision?"BOUND":turn.status==="RUNNING"?"WAIT":"—"));
  if(operation){
    const authorityDetail=operation.ticket_id?(operation.capability+" · "+operation.ticket_id):(operation.capability+" · intent recorded");
    const opState=operation.state==="RESOLVED"?"done":operation.state==="UNKNOWN"?"unknown":"active";
    box.append(spineStep("Ticket",authorityDetail,opState,operation.state));
  }else{
    box.append(spineStep("Authority",decision?.decision_type==="tool_call"?"Proposal has not received a durable tool Ticket.":"No external tool admitted in the latest step.",decision?.decision_type==="tool_call"?"active":"",decision?.decision_type==="tool_call"?"CHECK":"—"));
  }
  let resultDetail="No durable tool result in the latest step.",resultState="",resultLabel="—";
  if(result){
    if(result.error){resultDetail=result.error;resultState="unknown";resultLabel="CHECK";}
    else{
      resultState="done";resultLabel="RECORDED";
      if(result.evidence_ref)resultDetail=result.evidence_ref;
      else if(result.artifact?.name)resultDetail="artifact · "+result.artifact.name;
      else if(result.matches?.length!==undefined)resultDetail=result.matches.length+" project matches";
      else if(result.output!==undefined)resultDetail=(result.output||"clean").slice(0,160);
      else if(result.sources?.length)resultDetail=result.sources.length+" sources recorded";
      else if(result.value!==undefined)resultDetail="value · "+result.value;
      else resultDetail="Tool result persisted.";
    }
  }
  box.append(spineStep("Result",resultDetail,resultState,resultLabel));
  let completionDetail="Awaiting the assistant answer.",completionState="",completionLabel="—";
  if(turn.status==="COMPLETED"){completionDetail="Conversation answer completed. Semantic goal verification is not claimed.";completionState="done";completionLabel="ANSWERED";}
  else if(turn.status==="WAITING_USER"){completionDetail="Agent is waiting for user input.";completionState="active";completionLabel="USER";}
  else if(turn.status==="PAUSED"){completionDetail="Paused at a safe point. Existing Tickets remain factual.";completionState="active";completionLabel="PAUSED";}
  else if(turn.status==="UNKNOWN"){completionDetail=turn.error||"Execution outcome is uncertain and must be reconciled.";completionState="unknown";completionLabel="UNKNOWN";}
  else if(["FAILED","CANCELLED","BUDGET_EXHAUSTED"].includes(turn.status)){completionDetail=turn.error||turn.status;completionState="unknown";completionLabel=turn.status;}
  box.append(spineStep("Completion",completionDetail,completionState,completionLabel));
}

function renderInspectorBudgets(turn){
  const box=$("inspectorBudgets");if(!box)return;box.replaceChildren();
  const rows=turn?.budgets||[];if(!rows.length){box.append(el("div","inspector-empty","暂无运行预算"));return;}
  rows.forEach(row=>{const wrap=el("div","budget-row"),head=el("div","budget-head");head.append(el("strong","",row.meter),el("span","",(row.settled||0)+" / "+(row.limit_units||0)));const track=el("div","budget-track"),used=el("div","budget-used"),limit=Math.max(1,Number(row.limit_units||0));used.style.width=Math.min(100,((Number(row.settled||0)+Number(row.reserved||0))/limit)*100)+"%";track.append(used);if(Number(row.unknown_held||0)>0){const unknown=el("div","budget-unknown");unknown.style.width=Math.min(100,(Number(row.unknown_held)/limit)*100)+"%";track.append(unknown);}wrap.append(head,track);box.append(wrap);});
}

function renderInspectorControl(turn){
  const box=$("inspectorControl");if(!box)return;box.replaceChildren();
  if(!turn){box.append(el("div","inspector-empty","暂无 Control state"));return;}
  const control=turn.control||{};
  [["revision",control.revision||1],["model",control.model||turn.settings?.model||"—"],["thinking",control.thinking===true?"on":control.thinking===false?"off":control.thinking||"default"],["steering",control.steering_note||"—"]].forEach(([k,v])=>{const row=el("div","context-fact");row.append(el("span","",k),el("span","",v));box.append(row);});
}

function renderInspectorContext(session,turn){
  const box=$("inspectorContext");if(!box)return;box.replaceChildren();
  if(!session&&!turn){box.append(el("div","inspector-empty","暂无活动上下文"));return;}
  const snapshot=turn?.snapshot||{},project=snapshot.project||null;
  [["Project",project?.name||session?.project_name||"Independent"],["History",(snapshot.messages?.length||session?.messages?.length||0)+" messages"],["Knowledge",(snapshot.knowledge?.length||0)+" sources"],["Memory",(snapshot.memory?.length||0)+" records"],["Events",(turn?.events?.length||0)+""],["Step",turn?((turn.current_step||0)+" / "+(turn.max_steps||0)):"—"]].forEach(([k,v])=>{const row=el("div","context-fact");row.append(el("span","",k),el("span","",v));box.append(row);});
}

function renderInspectorPlatform(){
  const box=$("inspectorPlatform");if(!box)return;box.replaceChildren();const counts={usable:0,wired:0,planned:0};
  (state.data?.platform?.layers||[]).forEach(layer=>{if(counts[layer.state]!==undefined)counts[layer.state]++;});
  ["usable","wired","planned"].forEach(key=>{const card=el("div",key);card.append(el("strong","",counts[key]),el("small","",key));box.append(card);});
}

function renderRuntimeInspector(session=state.session){
  const turn=session?.turns?.at(-1)||null,[label,cls]=inspectorStatus(turn?.status||"IDLE");
  if($("inspectorState"))$("inspectorState").textContent=label;
  if($("inspectorPulse"))$("inspectorPulse").className="inspector-pulse "+cls;
  renderExecutionSpine(turn);renderInspectorControl(turn);renderInspectorBudgets(turn);renderInspectorContext(session,turn);renderInspectorPlatform();
}

function fitPromptInspector(){const prompt=$("prompt");if(!prompt)return;prompt.style.height="auto";prompt.style.height=Math.min(160,Math.max(30,prompt.scrollHeight))+"px";}
function syncNavCurrent(){document.querySelectorAll("[data-page]").forEach(link=>{if(link.classList.contains("active"))link.setAttribute("aria-current","page");else link.removeAttribute("aria-current");});}
if($("prompt")){$("prompt").addEventListener("input",fitPromptInspector);fitPromptInspector();}
window.addEventListener("hashchange",()=>setTimeout(()=>{syncNavCurrent();renderRuntimeInspector();},0));
setInterval(()=>{syncNavCurrent();renderRuntimeInspector();},700);
setTimeout(()=>{syncNavCurrent();renderRuntimeInspector();},0);
