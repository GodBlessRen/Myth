import {FormEvent,useState} from "react";
import {useQuery} from "@tanstack/react-query";
import {CalendarClock,History,Pause,Play,Plus,Target} from "lucide-react";
import {workspace} from "../api";
import {navigate,useRefresh} from "../workspace";
import {asRecord,displayValue,statusText} from "../types";
import type {Bootstrap,Goal,UnknownRecord} from "../types";

type Schedule=UnknownRecord & {schedule_id?:string;goal_id?:string;session_id?:string;enabled?:boolean;prompt?:string;due_at?:string;interval_seconds?:number|null};
type Props={data:Bootstrap;notify:(message:string)=>void};
export function Goals({data,notify}:Props){
  const refresh=useRefresh();
  const [newOpen,setNewOpen]=useState(false),[title,setTitle]=useState(""),[description,setDescription]=useState("");
  const [scheduleFor,setScheduleFor]=useState<Goal|null>(null);
  const [schedulePrompt,setSchedulePrompt]=useState(""),[scheduleSession,setScheduleSession]=useState("");
  const [due,setDue]=useState(""),[interval,setIntervalValue]=useState(""),[scheduleRequest,setScheduleRequest]=useState("");
  const [busy,setBusy]=useState(false);
  const schedules=useQuery({queryKey:["workspace","schedules"],queryFn:()=>workspace.read<{schedules:Schedule[];scheduler?:UnknownRecord}>("/schedules"),refetchInterval:12000});
  async function act(path:string,body:unknown){
    if(busy)return false;setBusy(true);
    try{await workspace.post(path,body);await refresh();await schedules.refetch();return true;}
    catch(error){notify(error instanceof Error?error.message:"操作失败");return false;}
    finally{setBusy(false);}
  }
  const newGoal=async(e:FormEvent)=>{
    e.preventDefault();
    if(await act("/goals",{title,description})){setNewOpen(false);setTitle("");setDescription("");notify("目标已保存，可跨会话继续推进。");}
  };
  const planGoal=(goal:Goal)=>{
    setScheduleFor(goal);setScheduleSession(data.sessions[0]?.id||"");
    setSchedulePrompt(String(asRecord(goal.work).next_action||""));
    const d=new Date(Date.now()+5*60*1000);
    setDue(new Date(d.getTime()-d.getTimezoneOffset()*60_000).toISOString().slice(0,16));
    setIntervalValue("");setScheduleRequest(crypto.randomUUID());
  };
  const saveSchedule=async(e:FormEvent)=>{
    e.preventDefault();
    if(!scheduleFor||!scheduleSession||!due)return;
    if(await act("/goals/"+encodeURIComponent(scheduleFor.goal_id)+"/schedules",{
      session_id:scheduleSession,prompt:schedulePrompt,request_id:scheduleRequest,
      due_at:new Date(due).toISOString(),interval_seconds:interval?Number(interval):null,
    })){setScheduleFor(null);notify("工作计划已保存");}
  };
  const rows=schedules.data?.schedules||[];
  return <section className="content-page"><header className="page-header"><div><span className="micro-label">MYTH / LONG-RUN</span><h1>目标与计划</h1><p>从长期目标到下一次执行，状态与完成证据分别保存。</p></div>
    <button className="solid-action" onClick={()=>setNewOpen(true)}><Plus size={17}/>新建目标</button></header>
    <p className="subtext">{schedules.data?.scheduler?.running?"定时唤醒正在运行":"定时唤醒未运行或状态未报告"} · 页面读取不会触发执行</p>
    <div className="goal-grid">{data.goals.length?data.goals.map(goal=>{
      const work=asRecord(goal.work);
      const goalSchedules=rows.filter(s=>s.goal_id===goal.goal_id);
      return <article className="goal-card" key={goal.goal_id}>
        <header><div><Target size={18}/><h2>{goal.title}</h2></div><span className="state-lozenge">{statusText(goal.state)}</span></header>
        <p>{goal.description||displayValue(work.progress_note)}</p>
        <div className="goal-progress"><span>当前阶段</span><strong>{statusText(String(work.current_state||"READY"))}</strong></div>
        <p className="subtext">下一步 · {displayValue(work.next_action)}</p>
        <div className="button-row"><button className="subtle-button" onClick={async()=>{
          try{const result=await workspace.read<{runs:Array<{session_id:string}>}>("/goals/"+encodeURIComponent(goal.goal_id)+"/runs");
            const latest=result.runs.at(-1);navigate("chat",latest?.session_id);}catch(error){notify(error instanceof Error?error.message:"读取失败");}
        }}><History size={14}/>继续工作</button>
        <button className="subtle-button" disabled={busy||goal.state!=="ACTIVE"} onClick={()=>planGoal(goal)}><CalendarClock size={14}/>安排计划</button>
        <button className="subtle-button" disabled={busy||!["ACTIVE","PAUSED"].includes(goal.state||"")} onClick={()=>void act("/goals/"+encodeURIComponent(goal.goal_id)+"/state",{state:goal.state==="PAUSED"?"ACTIVE":"PAUSED"})}>
          {goal.state==="PAUSED"?<Play size={14}/>:<Pause size={14}/>}{goal.state==="PAUSED"?"恢复":"暂停"}</button></div>
        {goalSchedules.length?<details className="schedule-panel"><summary>{goalSchedules.length} 项工作计划</summary>{goalSchedules.map(s=><div className="schedule-line" key={s.schedule_id}>
          <div><strong>{s.enabled?"已启用":"已暂停 / 已结束"}</strong><p>{s.prompt}</p><small>{s.due_at||"时间未报告"}</small></div>
          <button disabled={busy} onClick={()=>void act("/schedules/"+encodeURIComponent(s.schedule_id||"")+"/enabled",{enabled:!s.enabled})}>{s.enabled?"暂停":"启用"}</button>
        </div>)}</details>:null}
      </article>;
    }):<div className="list-empty">还没有长期目标。先保存目标，再安排工作。</div>}</div>
    {newOpen?<div className="modal-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget)setNewOpen(false);}}><form className="dialog-card" role="dialog" aria-modal="true" aria-label="新建长期目标" onSubmit={e=>void newGoal(e)}>
      <h2>新建长期目标</h2><label>目标<input required maxLength={200} value={title} onChange={e=>setTitle(e.target.value)}/></label>
      <label>完成标准与约束<textarea rows={4} value={description} onChange={e=>setDescription(e.target.value)}/></label>
      <div className="dialog-actions"><button data-dialog-close type="button" onClick={()=>setNewOpen(false)}>取消</button><button className="solid-action" disabled={busy||!title.trim()}>创建目标</button></div>
    </form></div>:null}
    {scheduleFor?<div className="modal-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget)setScheduleFor(null);}}><form className="dialog-card" role="dialog" aria-modal="true" aria-label="安排下一次工作" onSubmit={e=>void saveSchedule(e)}>
      <h2>安排下一次工作</h2><p>{scheduleFor.title}</p>
      <label>目标会话<select required value={scheduleSession} onChange={e=>setScheduleSession(e.target.value)}>
        <option value="">选择会话</option>{data.sessions.map(s=><option key={s.id} value={s.id}>{s.title}</option>)}</select></label>
      {!data.sessions.length?<p className="inline-error">请先创建一个会话，再安排计划。</p>:null}
      <label>执行任务<textarea required value={schedulePrompt} rows={4} onChange={e=>setSchedulePrompt(e.target.value)}/></label>
      <label>首次开始（本地时间）<input required type="datetime-local" value={due} onChange={e=>setDue(e.target.value)}/></label>
      <label>重复<select value={interval} onChange={e=>setIntervalValue(e.target.value)}><option value="">仅一次</option><option value="600">每10分钟</option><option value="3600">每小时</option><option value="86400">每天</option></select></label>
      <p className="subtext">执行设置由当前 Python Runtime 校验，失败后原 Request ID 保留。</p>
      <div className="dialog-actions"><button data-dialog-close type="button" onClick={()=>setScheduleFor(null)}>取消</button><button className="solid-action" disabled={busy||!scheduleSession||!schedulePrompt||!due}>保存计划</button></div>
    </form></div>:null}
  </section>;
}
