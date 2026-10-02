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

function inspectorFact(box,key,value){
  const row=el("div","context-fact");
  row.append(el("span","",key),el("span","",value??"—"));
  box.append(row);
}

function renderInspectorGoal(turn){
  const box=$("inspectorGoal");if(!box)return;box.replaceChildren();
  const goal=turn?.goal_current||turn?.snapshot?.goal;
  if(!goal?.goal_id){box.append(el("div","inspector-empty","暂无长期 Goal"));return;}
  const work=goal.work||{};
  inspectorFact(box,"Goal",goal.title||goal.goal_id);
  inspectorFact(box,"State",work.current_state||goal.state||"—");
  inspectorFact(box,"Progress",work.progress_note||"—");
  inspectorFact(box,"Next",work.next_action||"—");
  if(work.waiting_for)inspectorFact(box,"Waiting",work.waiting_for);
  inspectorFact(box,"Revision",work.revision||"—");
}

function renderInspectorTokens(turn){
  const box=$("inspectorTokens");if(!box)return;box.replaceChildren();
  if(!turn){box.append(el("div","inspector-empty","暂无 Token 使用"));return;}
  const byMeter=Object.fromEntries((turn.budgets||[]).map(row=>[row.meter,row]));
  const input=byMeter.input_tokens||{},output=byMeter.output_tokens||{},calls=byMeter.model_calls||{};
  inspectorFact(box,"Context window",turn.settings?.num_ctx?turn.settings.num_ctx+" tokens":"provider-managed");
  inspectorFact(box,"Input settled",Number(input.settled||0).toLocaleString());
  inspectorFact(box,"Output settled",Number(output.settled||0).toLocaleString());
  inspectorFact(box,"Model calls",Number(calls.settled||0)+" / "+Number(calls.limit_units||0));
  if(Number(input.unknown_held||0)||Number(output.unknown_held||0))inspectorFact(box,"Unknown held",Number(input.unknown_held||0)+" in · "+Number(output.unknown_held||0)+" out");
}

function renderInspectorTrajectory(turn){
  const box=$("inspectorTrajectory");if(!box)return;box.replaceChildren();
  const events=(turn?.events||[]).slice(-14);
  if(!events.length){box.append(el("div","inspector-empty","暂无轨迹"));return;}
  events.forEach(event=>{
    const row=el("div","trajectory-row");
    row.append(el("span","trajectory-seq","#"+event.sequence),el("strong","",event.kind));
    const payload=event.payload||{};
    const detail=payload.capability||payload.status||payload.intent_route||payload.model_attempt_id||payload.reason||"";
    if(detail)row.append(el("small","",String(detail).slice(0,120)));
    box.append(row);
  });
}

function renderInspectorTools(turn){
  const box=$("inspectorTools");if(!box)return;box.replaceChildren();
  const ops=turn?.operations||[];
  if(!ops.length){box.append(el("div","inspector-empty","暂无工具调用"));return;}
  ops.slice(-8).forEach(op=>{
    const row=el("div","observatory-tool");
    const head=el("div","observatory-tool-head");
    head.append(el("strong","",op.capability||"tool"),el("span","",op.state||""));
    row.append(head);
    const identity=op.ticket_id||op.decision_id;
    if(identity)row.append(el("small","",identity));
    if(op.result?.artifact?.name)row.append(el("small","","artifact · "+op.result.artifact.name));
    else if(op.result?.error)row.append(el("small","",op.result.error));
    box.append(row);
  });
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
  [["revision",control.revision||1],["status",(control.stopped??control.aborted)?"stopped":control.paused?"paused":"active"],["model",control.model||turn.settings?.model||"—"],["thinking",control.thinking===true?"on":control.thinking===false?"off":control.thinking||"default"],["steering",control.steering_note||"—"]].forEach(([k,v])=>{const row=el("div","context-fact");row.append(el("span","",k),el("span","",v));box.append(row);});
}

function renderInspectorContext(session,turn){
  const box=$("inspectorContext");if(!box)return;box.replaceChildren();
  if(!session&&!turn){box.append(el("div","inspector-empty","暂无活动上下文"));return;}
  const snapshot=turn?.snapshot||{},project=snapshot.project||null;
  [["Project",project?.name||session?.project_name||"Independent"],["History",(snapshot.messages?.length||session?.messages?.length||0)+" messages"],["Knowledge",(snapshot.knowledge?.length||0)+" sources"],["Memory",(snapshot.memory?.length||0)+" records"],["Events",(turn?.events?.length||0)+""],["Step",turn?((turn.current_step||0)+" / "+(turn.max_steps||0)):"—"]].forEach(([k,v])=>{const row=el("div","context-fact");row.append(el("span","",k),el("span","",v));box.append(row);});
  const compiled=(turn?.events||[]).filter(event=>event.kind==="ConversationContextCompiled").at(-1)?.payload;
  if(compiled){
    const pct=compiled.max_bytes?Math.round((compiled.bytes_used/compiled.max_bytes)*100):0;
    [["模型上下文",compiled.bytes_used+" / "+compiled.max_bytes+" bytes · "+pct+"%"],["Token window",compiled.num_ctx?compiled.num_ctx+" tokens":"provider-managed"],["实际选入",(compiled.selected?.length||0)+" 项"],["旧记录折叠",(compiled.folded?.length||0)+" 项"],["未选入",(compiled.dropped?.length||0)+" 项"]].forEach(([k,v])=>{const row=el("div","context-fact");row.append(el("span","",k),el("span","",v));box.append(row);});
  }
}

function renderInspectorPlatform(){
  const box=$("inspectorPlatform");if(!box)return;box.replaceChildren();
  const counts={hardened:0,usable:0,connected:0,exists:0,planned:0};
  const platform=state.data?.platform||{};
  [...(platform.core||[]),...(platform.domains||[]),...(platform.strategies||[]),...(platform.adapters||[])].forEach(item=>{
    const maturity=item.maturity||item.state;
    if(counts[maturity]!==undefined)counts[maturity]++;
  });
  ["hardened","usable","connected","exists","planned"].forEach(key=>{
    const card=el("div",key);card.append(el("strong","",counts[key]),el("small","",key));box.append(card);
  });
}

function renderRuntimeInspector(session=state.session){
  const turn=session?.turns?.at(-1)||null,[label,cls]=inspectorStatus(turn?.status||"IDLE");
  if($("inspectorState"))$("inspectorState").textContent=label;
  if($("inspectorPulse"))$("inspectorPulse").className="inspector-pulse "+cls;
  renderInspectorGoal(turn);renderExecutionSpine(turn);renderInspectorTrajectory(turn);renderInspectorTokens(turn);renderInspectorContext(session,turn);renderInspectorTools(turn);renderInspectorControl(turn);renderInspectorBudgets(turn);renderInspectorPlatform();
}

function fitPromptInspector(){const prompt=$("prompt");if(!prompt)return;prompt.style.height="auto";prompt.style.height=Math.min(160,Math.max(30,prompt.scrollHeight))+"px";}
function syncNavCurrent(){document.querySelectorAll("[data-page]").forEach(link=>{if(link.classList.contains("active"))link.setAttribute("aria-current","page");else link.removeAttribute("aria-current");});}
if($("prompt")){$("prompt").addEventListener("input",fitPromptInspector);fitPromptInspector();}
window.addEventListener("hashchange",()=>setTimeout(()=>{syncNavCurrent();renderRuntimeInspector();},0));
setInterval(()=>{syncNavCurrent();renderRuntimeInspector();},700);
setTimeout(()=>{syncNavCurrent();renderRuntimeInspector();},0);
