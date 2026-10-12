import {useMemo} from "react";
import {Activity, Bot, CheckCircle2, CircleHelp, Cpu, GitBranch, History, Layers, Terminal, Wallet} from "lucide-react";
import type {Session,Turn,UnknownRecord} from "../types";
import {asRecord,displayValue,statusText} from "../types";
import {useUi} from "../store";

function records(x:unknown):UnknownRecord[]{return Array.isArray(x)?x.map(asRecord):[];}
function Fact({label,value}:{label:string;value:unknown}){
  return <div className="fact"><span>{label}</span><strong>{displayValue(value)}</strong></div>;
}
function Empty({children}:{children:string}){return <p className="empty-fact">{children}</p>;}
function Part({title,children,opened=true}:{title:string;children:React.ReactNode;opened?:boolean}){
  return <details className="inspector-part" defaultOpen={opened}><summary>{title}<span className="fold-visual">⌄</span></summary><div>{children}</div></details>;
}
function Graph({turn}:{turn:Turn|null}){
  const graph=asRecord(turn?.execution_graph);
  const nodes=records(graph.nodes);
  return nodes.length?<div className="graph-list">{nodes.map((node,i)=><div className="graph-node" key={String(node.id||i)} style={{paddingLeft:Math.max(0,Math.min(4,Number(node.depth)||0))*12}}>
    <span className="graph-mark">{i===0?"●":node.kind==="subagent"?"↳":"↓"}</span>
    <div><strong>{displayValue(node.label||node.kind||"节点")}</strong><small>{displayValue(node.detail)}</small>
      {node.model?<small>{displayValue(node.provider)} · {displayValue(node.model)}</small>:null}</div>
    <span className={"state-text state-"+String(node.state||"UNKNOWN").toLowerCase()}>{statusText(String(node.state||"UNKNOWN"))}</span>
  </div>)}</div>:<Empty>暂无可投影的执行图</Empty>;
}
function TokenMetrics({turn}:{turn:Turn}){
  const usage=asRecord(turn.model_usage), samples=asRecord(usage.measurement_samples);
  const budgets=records(asRecord(turn).budgets);
  const settled=(key:string)=>budgets.find(r=>r.meter===key)?.settled;
  const coverage=(name:string,value:unknown)=>
    `${displayValue(value)} · ${displayValue(samples[name])} / ${displayValue(usage.model_calls)} 次报告`;
  const cacheRate=typeof usage.cache_hit_rate==="number"&&usage.cache_hit_rate>=0&&usage.cache_hit_rate<=1
    ?(usage.cache_hit_rate*100).toFixed(1)+"%":"N/A · 供应商未报告";
  return <>
    <Fact label="Context window" value={turn.settings?.num_ctx??"供应商管理"}/>
    <Fact label="Input settled" value={settled("input_tokens")}/>
    <Fact label="Output settled" value={settled("output_tokens")}/>
    <Fact label="Input reported" value={coverage("input_tokens",usage.input_tokens)}/>
    <Fact label="Output reported" value={coverage("output_tokens",usage.output_tokens)}/>
    <Fact label="Cache reported" value={coverage("cached_input_tokens",usage.cached_input_tokens)}/>
    <Fact label="Cache hit" value={cacheRate}/>
    <Fact label="First token" value={usage.first_token_ms==null?"N/A · 未报告":displayValue(usage.first_token_ms)+" ms"}/>
    <Fact label="Model wall" value={coverage("provider_wall_ms",usage.provider_wall_ms)}/>
  </>;
}
function BudgetList({turn}:{turn:Turn}){
  const budgets=records(asRecord(turn).budgets);
  return budgets.length?budgets.map((b,i)=>{
    const limit=Number(b.limit_units),settled=Number(b.settled||0),reserved=Number(b.reserved||0),unknown=Number(b.unknown_held||0);
    const percent=(n:number)=>Number.isFinite(limit)&&limit>0?Math.max(0,Math.min(100,n/limit*100)):0;
    return <div className="budget-meter" key={String(b.meter||i)}>
      <div className="budget-title"><strong>{displayValue(b.meter)}</strong><span>{displayValue(b.settled)} / {displayValue(b.limit_units)}</span></div>
      {limit>0?<div className="meter-track" aria-hidden="true"><i style={{width:percent(settled)+"%"}}/><i className="reserved" style={{width:percent(reserved)+"%"}}/><i className="unknown" style={{width:percent(unknown)+"%"}}/></div>:null}
      <small>预留 {displayValue(b.reserved)} · UNKNOWN {displayValue(b.unknown_held)}</small>
    </div>;
  }):<Empty>暂无预算数据</Empty>;
}
function Timeline({turn}:{turn:Turn}){
  const events=records(turn.events);
  return events.length?<div className="timeline">{events.slice(-30).map((event,i)=>{
    const payload=asRecord(event.payload);
    return <div className="timeline-item" key={String(event.sequence??i)}>
      <small>#{displayValue(event.sequence)}</small><div><strong>{displayValue(event.kind)}</strong><p>{displayValue(payload.capability||payload.status||payload.reason||payload.intent_route||"")}</p></div>
    </div>;
  })}</div>:<Empty>尚无持久执行轨迹</Empty>;
}
function Tools({turn}:{turn:Turn}){
  const ops=records(turn.operations);
  return ops.length?<div className="tool-items">{ops.slice(-12).map((op,i)=><details className="tool-entry" key={String(op.ticket_id||op.decision_id||i)}>
    <summary><Terminal size={14}/><span>{displayValue(op.capability||"Tool")}</span><em>{statusText(String(op.state||"UNKNOWN"))}</em></summary>
    <pre>{JSON.stringify(op,null,2)}</pre>
  </details>)}</div>:<Empty>尚未调用工具</Empty>;
}
export function Observatory({session}:{session:Session|null}){
  const {inspector,setInspector,lens,setLens}=useUi();
  const turn=useMemo(()=>session?.turns.at(-1)??null,[session]);
  const evidence=asRecord(turn?.provider_evidence);
  const tabs=[{id:"overview",name:"概览",icon:Activity},{id:"execution",name:"执行",icon:GitBranch},{id:"resources",name:"资源",icon:Wallet}] as const;
  if(!inspector)return <button className="inspector-rail" onClick={()=>setInspector(true)} aria-label="展开运行观测"><Activity size={18}/><span>运行观测</span></button>;
  return <aside className="observatory" aria-label="Runtime Observatory">
    <header className="obs-header"><div><span className="micro-label">RUNTIME / OBSERVATORY</span><h2>运行观测</h2>
      <p><span className={"status-indicator state-"+(turn?.status||"IDLE").toLowerCase()}/>{statusText(turn?.status)}</p></div>
      <button className="icon-action" aria-label="收起观测栏" onClick={()=>setInspector(false)}><Layers size={17}/></button>
    </header>
    <div className="obs-tabs" role="tablist" aria-label="运行观测视图">{tabs.map(t=><button key={t.id} role="tab" aria-selected={lens===t.id} className={lens===t.id?"active":""} onClick={()=>setLens(t.id)}><t.icon size={14}/>{t.name}</button>)}</div>
    <div className="obs-scroll" role="tabpanel" aria-label={tabs.find(t=>t.id===lens)?.name}>
      {!turn?<div className="obs-awaiting"><Bot size={27}/><h3>等待一个工作任务</h3><p>运行后，这里展示来自 Runtime 的持久执行事实、用量及恢复状态。</p></div>:
      lens==="overview"?<>
        <div className="obs-feature"><small>当前执行 · Run</small><strong className={"state-text state-"+turn.status.toLowerCase()}>{statusText(turn.status)}</strong><code title={turn.run_id}>{turn.run_id.slice(0,18)}…</code></div>
        <Part title="会话统计"><Fact label="消息" value={session?.messages.length}/><Fact label="轮次" value={session?.turns.length}/>
          {Object.entries(session?.statistics||{}).filter(([,v])=>typeof v==="number"||typeof v==="string").slice(0,9).map(([k,v])=><Fact key={k} label={k} value={v}/>)}</Part>
        <Part title="Goal / 状态"><Fact label="关联 Goal" value={turn.goal_current?.title??turn.snapshot?.goal?.goal_id}/><Fact label="工作状态" value={asRecord(turn.goal_current?.work).current_state}/></Part>
        <Part title="交付与验收" opened={false}>{Object.entries(asRecord(turn.delivery)).length?
          <pre className="evidence-raw">{JSON.stringify(turn.delivery,null,2)}</pre>:<Empty>尚无交付验收事实</Empty>}</Part>
        <Part title="恢复提示"><Fact label="Driver active" value={turn.driver_active}/><Fact label="持久状态" value={turn.status}/><Fact label="控制修订" value={turn.control?.revision}/>{turn.error?<pre className="evidence-raw">{turn.error}</pre>:null}</Part>
      </>:lens==="execution"?<>
        <Part title="执行图 · Execution Graph"><Graph turn={turn}/></Part>
        <Part title="持久执行轨迹"><Timeline turn={turn}/></Part>
        <Part title="工具调用"><Tools turn={turn}/></Part>
        <Part title="控制快照" opened={false}><pre className="evidence-raw">{JSON.stringify(turn.control||{},null,2)}</pre></Part>
      </>:<>
        <Part title="模型调用"><Fact label="Provider" value={evidence.provider_name||evidence.provider||turn.settings?.provider}/><Fact label="Model" value={evidence.model||turn.settings?.model}/><Fact label="Response" value={evidence.response_id}/><Fact label="Reasoning" value={evidence.reasoning_tokens}/>
          <details className="raw-disclosure"><summary><CircleHelp size={14}/>公开 Provider 元数据</summary><pre className="evidence-raw">{JSON.stringify(evidence,null,2)}</pre></details></Part>
        <Part title="Token / 缓存"><TokenMetrics turn={turn}/></Part>
        <Part title="运行预算"><BudgetList turn={turn}/></Part>
        <Part title="SOTA Route" opened={false}><pre className="evidence-raw">{JSON.stringify(turn.sota_route||{},null,2)}</pre></Part>
        <Part title="执行进度" opened={false}><Fact label="步骤" value={turn.current_step}/><Fact label="上限" value={turn.max_steps}/></Part>
      </>}
    </div>
    <footer className="obs-footer"><CheckCircle2 size={15}/>事实来自 Python Runtime 快照</footer>
  </aside>;
}
