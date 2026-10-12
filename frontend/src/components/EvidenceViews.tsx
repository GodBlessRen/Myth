import {useState} from "react";
import {GitBranch,GitCompareArrows} from "lucide-react";
import {asRecord,displayValue,statusText} from "../types";
import type {Turn,UnknownRecord} from "../types";

// 只消费 Runtime 已保存的执行图和工具收据；关系、费用、UNKNOWN 均不得由前端补造。
export type DiffRecord={id:string;capability:string;path:string;diff:string;truncated:boolean};
const rows=(value:unknown):UnknownRecord[]=>Array.isArray(value)?value.map(asRecord):[];
export function collectDiffs(turn:Turn|null):DiffRecord[]{
  if(!turn)return [];
  const result:DiffRecord[]=[];
  const add=(id:string,capability:string,data:unknown)=>{
    if(!["diff.preview","git.diff","project.patch_exact"].includes(capability))return;
    const outer=asRecord(data),nested=asRecord(outer.result);
    const record=Object.keys(nested).length?nested:outer;
    const raw=typeof record.diff==="string"?record.diff:
      capability==="git.diff"&&typeof record.output==="string"?record.output:null;
    if(raw===null)return;
    result.push({id,capability,path:typeof record.path==="string"?record.path:"",
      diff:raw,truncated:record.truncated===true});
  };
  rows(turn.activities).forEach((step,i)=>{
    const decision=asRecord(step.decision);
    add("step-"+String(step.step??i),String(decision.capability_id||decision.action||""),step.result);
  });
  rows(turn.operations).forEach((op,i)=>{
    add(String(op.decision_id||op.ticket_id||i),String(op.capability||""),op.result);
  });
  // 一个工具决定及其同一收据可能出现在两个投影中，按内容身份去重。
  return result.filter((item,index)=>result.findIndex(other=>other.capability===item.capability&&
    other.path===item.path&&other.diff===item.diff)===index);
}
export function DiffEvidence({turn,compact=false}:{turn:Turn|null;compact?:boolean}){
  const changes=collectDiffs(turn);
  if(!changes.length)return compact?null:<p className="empty-fact">尚无 Diff 工具结果。不会根据对话文本猜测文件已修改。</p>;
  return <div className="diff-evidence" aria-label="文件差异证据">
    {changes.map(item=><details key={item.id} className="diff-entry">
      <summary><GitCompareArrows size={15}/><span>{item.capability} · {item.path||"项目工作区"}</span>
        {item.truncated?<small>仅展示后端有界片段</small>:null}</summary>
      {!item.diff?<p className="subtext">该操作没有内容差异。</p>:
        <pre className="diff-code" aria-label="统一 Diff，只读">
          {item.diff.split(/\r?\n/).map((line,i)=>{
            const kind=line.startsWith("+++")||line.startsWith("---")||line.startsWith("diff ")?
              "diff-meta":line.startsWith("@@")?"diff-hunk":line.startsWith("+")?"diff-added":
              line.startsWith("-")?"diff-removed":"diff-context";
            return <span className={kind} key={i}>{line}{"\n"}</span>;
          })}
        </pre>}
      <small className="subtext">这是工具投影的只读证据；Diff 预览不等于已写入文件或通过验收。</small>
    </details>)}
  </div>;
}
function Fact({label,value}:{label:string;value:unknown}){
  return <div className="fact"><span>{label}</span><strong>{displayValue(value)}</strong></div>;
}
export function ExecutionGraph({turn}:{turn:Turn|null}){
  const graph=asRecord(turn?.execution_graph);
  const nodes=rows(graph.nodes),edges=rows(graph.edges);
  const coverage=asRecord(graph.coverage),cost=asRecord(graph.cost_summary);
  const [selected,setSelected]=useState<string|null>(null);
  if(!nodes.length)return <p className="empty-fact">暂无持久执行图。尚未映射的 Attempt 不会被 UI 隐藏或补画。</p>;
  const current=nodes.find(n=>n.id===selected);
  return <div className="execution-evidence">
    <div className="graph-summary">
      <Fact label="已映射 Model Attempt" value={coverage.mapped_model_calls}/>
      <Fact label="未映射 Attempt" value={coverage.unmapped_model_calls}/>
      <Fact label="成本未知调用" value={cost.unknown_calls}/>
      <Fact label="调用总数" value={cost.model_calls}/>
    </div>
    <div className="graph-list" role="list" aria-label="执行图节点">
      {nodes.map((node,i)=>{
        const id=String(node.id||i),level=Math.max(0,Math.min(3,Number(node.depth)||0));
        const isChild=node.kind==="subagent",route=asRecord(node.routing),review=asRecord(node.review);
        const nodeCost=asRecord(node.cost);
        const incoming=edges.filter(e=>e.target===id);
        const relation=incoming.map(e=>String(e.kind||"next")).join(" / ");
        return <div className={"graph-node "+(isChild?"graph-subagent":"")} key={id} role="listitem" style={{paddingLeft:level*12}}>
          <span className="graph-mark" aria-hidden="true">{isChild?"↳":node.kind==="tool"?"↓":"●"}</span>
          <button type="button" className="graph-node-detail" onClick={()=>setSelected(selected===id?null:id)}
            aria-expanded={selected===id} aria-label={"查看节点证据 "+String(node.label||node.kind||"")}>
            <strong>{displayValue(node.label||node.kind||"节点")}</strong>
            <small>{displayValue(node.detail)}{relation?" · "+relation:""}</small>
            {node.model?<small>{displayValue(node.provider)} · {displayValue(node.model)}</small>:null}
            {route.task_type?<small>路由 {displayValue(route.task_type)} / {displayValue(route.difficulty)}</small>:null}
            {review.delegation_id?<small>审核 {review.accepted===true?"采用":review.accepted===false?"拒收":"待确认"} · {displayValue(review.metadata_verdict)}</small>:null}
            {nodeCost.amount!=null?<small>估算 {displayValue(nodeCost.amount)} {displayValue(nodeCost.currency)}</small>:null}
          </button>
          <span className={"state-text state-"+String(node.state||"UNKNOWN").toLowerCase()}>{statusText(String(node.state||"UNKNOWN"))}</span>
        </div>;
      })}
    </div>
    {current?<section className="graph-details" aria-label="所选执行节点的完整公开事实">
      <div className="button-row"><strong>{displayValue(current.label)}</strong>
        <button type="button" onClick={()=>setSelected(null)}>关闭详情</button></div>
      <Fact label="Attempt" value={current.attempt_id}/>
      <Fact label="Ticket" value={current.ticket_id}/>
      <Fact label="批次 / 顺序" value={current.batch_id?String(current.batch_id)+" / "+displayValue(current.ordinal):null}/>
      <Fact label="状态" value={current.state}/>
      <pre className="evidence-raw">{JSON.stringify({
        routing:current.routing??null,review:current.review??null,usage:current.usage??null,
        cost:current.cost??null,edges:edges.filter(e=>e.source===current.id||e.target===current.id)
      },null,2)}</pre>
    </section>:null}
    <details className="raw-disclosure"><summary><GitBranch size={14}/>费用及映射覆盖率 · Runtime 事实</summary>
      <pre className="evidence-raw">{JSON.stringify({coverage,cost_summary:cost},null,2)}</pre>
      <small className="subtext">仅使用已配置的标价估算；按 review 状态分桶，费用缺测不表示 0。</small>
    </details>
  </div>;
}
