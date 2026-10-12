import {FormEvent,useEffect,useRef,useState} from "react";
import {ArrowDown,ArrowUp,BookOpen,Check,ClipboardCopy,FileText,MessageSquarePlus,Pause,Play,Send,Square,StepForward,Target,Workflow} from "lucide-react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {workspace,pendingRequestId,clearPending,ApiError} from "../api";
import {navigate,useRefresh} from "../workspace";
import {activeStatus,finalStatus,statusText,displayValue} from "../types";
import type {Artifact,Bootstrap,Message,Session,Turn,UnknownRecord} from "../types";

type Props={
  bootstrap:Bootstrap; session:Session|null; sessionId:string|null;
  loading:boolean; loadError?:string; notify:(message:string)=>void;
};
function OperationGroup({turn}:{turn:Turn}){
  const operations=turn.operations||[];
  if(!operations.length && !turn.activities?.length)return null;
  return <details className="operation-group">
    <summary><Workflow size={15}/><span>{operations.length} 次工具调用 · {turn.activities?.length||0} 个决策步骤</span><span className="operation-state">{statusText(turn.status)}</span></summary>
    <div className="operation-body">{operations.map((op,i)=><details key={String(op.ticket_id||op.decision_id||i)} className="operation-line">
      <summary><strong>{displayValue(op.capability||"工具")}</strong><small>{statusText(String(op.state||"UNKNOWN"))}</small></summary>
      <pre>{JSON.stringify(op,null,2)}</pre>
    </details>)}</div>
  </details>;
}
function ArtifactRow({artifact}:{artifact:Artifact}) {
  return <a className="artifact-row" href={"/api/workspace/artifacts/"+encodeURIComponent(artifact.decision_id)} download>
    <FileText size={18}/><span><strong>{artifact.title||artifact.name||"执行产物"}</strong><small>下载持久化产物</small></span><ArrowDown size={16}/></a>;
}
function MessageRow({message}:{message:Message}){
  const [copied,setCopied]=useState(false);
  const onCopy=async()=>{
    try {await navigator.clipboard.writeText(message.content);setCopied(true);window.setTimeout(()=>setCopied(false),1600);}
    catch {setCopied(false);}
  };
  const isUser=message.role==="user";
  return <article className={"message-row "+(isUser?"from-user":"from-myth")} data-message-id={message.id}>
    <div className="message-surface">
      {!isUser?<div className="message-byline">MYTH <span>· Assistant</span></div>:null}
      <div className="message-markdown">{isUser?<p className="preserved-text">{message.content}</p>:
        <Markdown remarkPlugins={[remarkGfm]} skipHtml>{message.content}</Markdown>}</div>
      {!isUser?<div className="message-foot">
        {typeof message.metadata?.reply_elapsed_seconds==="number"?<span title="从用户输入持久化到本次回复落库的端到端时间，非纯推理时长">{message.metadata.reply_elapsed_seconds}s · 端到端</span>:null}
        <button onClick={onCopy} type="button" aria-label="复制回复">{copied?<Check size={14}/>:<ClipboardCopy size={14}/>} {copied?"已复制":"复制"}</button>
        <a download href={"/api/workspace/messages/"+encodeURIComponent(message.id)+"/download"}>保存 Markdown</a>
      </div>:null}
    </div>
  </article>;
}
function Thread({session}:{session:Session}){
  const scrollRef=useRef<HTMLDivElement>(null);
  const follow=useRef(true);
  const previousSession=useRef<string|null>(null);
  const turnsByRun=new Map(session.turns.map(turn=>[turn.run_id,turn]));
  const artifactsByRun=new Map<string,Artifact[]>();
  session.artifacts.forEach(artifact=>{const key=artifact.run_id||"";artifactsByRun.set(key,[...(artifactsByRun.get(key)||[]),artifact]);});
  const last=session.turns.at(-1);
  useEffect(()=>{
    const node=scrollRef.current;if(!node)return;
    if(previousSession.current!==session.id){node.scrollTop=node.scrollHeight;previousSession.current=session.id;follow.current=true;}
    else if(follow.current)node.scrollTop=node.scrollHeight;
  },[session.id,session.messages,session.turns,last?.status]);
  const seenRun=new Set<string>();
  const seenArtifact=new Set<string>();
  return <div className="chat-thread-scroll" ref={scrollRef} onScroll={e=>{const n=e.currentTarget;follow.current=n.scrollHeight-n.scrollTop-n.clientHeight<130;}}>
    <div className="chat-thread">
      {session.messages.map(message=>{
        const turn=message.run_id?turnsByRun.get(message.run_id):undefined;
        const extras=message.role==="assistant"&&turn&&!seenRun.has(turn.run_id);
        if(extras)seenRun.add(turn!.run_id);
        return <div key={message.id} className="thread-block">
          {extras?<OperationGroup turn={turn!}/>:null}
          <MessageRow message={message}/>
          {extras?(artifactsByRun.get(turn!.run_id)||[]).map(artifact=>{
            seenArtifact.add(artifact.decision_id);return <ArtifactRow key={artifact.decision_id} artifact={artifact}/>;
          }):null}
        </div>;
      })}
      {session.artifacts.filter(a=>!seenArtifact.has(a.decision_id)).map(a=><ArtifactRow key={a.decision_id} artifact={a}/>)}
      {last?.status==="RUNNING"?<div className="live-work"><span className={last.driver_active?"working-pulse":""}/>{last.driver_active?"正在执行当前 Run…":"Driver 已断连，等待核对持久状态"}</div>:null}
    </div>
    {!follow.current?<button className="jump-latest" onClick={()=>{scrollRef.current?.scrollTo({top:scrollRef.current.scrollHeight,behavior:"smooth"});follow.current=true;}}><ArrowDown size={16}/>回到最新</button>:null}
  </div>;
}
export function Chat({bootstrap,session,sessionId,loading,loadError,notify}:Props){
  const [text,setText]=useState("");
  const [projectId,setProjectId]=useState("");
  const [goalId,setGoalId]=useState("");
  const [docs,setDocs]=useState<string[]>([]);
  const [busy,setBusy]=useState(false);
  const [controlBusy,setControlBusy]=useState(false);
  const [steering,setSteering]=useState(false);
  const [steerText,setSteerText]=useState("");
  const [controlModel,setControlModel]=useState("");
  const [controlThinking,setControlThinking]=useState("");
  const [attachOpen,setAttachOpen]=useState(false);
  const drafts=useRef(new Map<string,string>());
  const prevKey=useRef(sessionId||"new");
  const composing=useRef(false);
  const inputRef=useRef<HTMLTextAreaElement>(null);
  const refresh=useRefresh();
  const latest=session?.turns.at(-1);
  const busyRun=!!latest&&activeStatus.has(latest.status);
  const canSend=!!text.trim()&&!busy&&(!busyRun||latest?.status==="WAITING_USER");
  const currentKey=sessionId||"new";

  useEffect(()=>{
    if(prevKey.current!==currentKey){
      drafts.current.set(prevKey.current,text);
      setText(drafts.current.get(currentKey)||"");
      setDocs([]);
      prevKey.current=currentKey;
    }
  // Switching session must not import a draft belonging to a different identity.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  },[currentKey]);
  useEffect(()=>{if(session?.project_id)setProjectId(session.project_id);},[session?.project_id]);
  const edit=(value:string)=>{setText(value);drafts.current.set(currentKey,value);};

  const control=async(action:"pause"|"resume"|"stop"|"continue"|"steer"|"compact"|"switch_model"|"switch_thinking",payload:UnknownRecord={})=>{
    if(!latest||controlBusy)return;
    setControlBusy(true);
    try {await workspace.control(latest.run_id,action,payload);await refresh(sessionId);notify("控制命令已提交，请等待 Runtime 状态更新。");}
    catch(error){notify(error instanceof Error?error.message:"控制失败");}
    finally {setControlBusy(false);}
  };
  const send=async(e?:FormEvent)=>{
    e?.preventDefault();
    if(!canSend)return;
    const message=text.trim(),attached=[...docs],goal=goalId||null, settings=bootstrap.settings;
    setBusy(true);
    try{
      if(!settings.model){navigate("settings");throw new Error("请先在设置中选择并连接可用模型");}
      let sid=sessionId;
      if(!sid){
        // 创建会话接口不支持幂等；超时后绝不自动重发创建请求。
        const result=await workspace.post<{id:string}>("/sessions",{project_id:projectId||null});
        sid=result.id;
      }
      if(latest?.status==="WAITING_USER"){
        await workspace.control(latest.run_id,"answer",{text:message,question_id:latest.question_id});
      }else{
        const full=attached.length?message+"\n\n本轮附加资料：\n"+attached.map(id=>{
          const doc=bootstrap.documents.find(d=>d.id===id);return "[doc:"+id+":0] "+(doc?.title||id);
        }).join("\n"):message;
        const fingerprint=[sid,full,attached,settings,goal];
        const requestId=await pendingRequestId(sid,fingerprint);
        await workspace.post("/sessions/"+encodeURIComponent(sid)+"/messages",
          {text:full,request_id:requestId,document_ids:attached,goal_id:goal});
        clearPending(sid);
      }
      edit("");setDocs([]);
      await refresh(sid);
      if(sid!==sessionId)navigate("chat",sid);
    }catch(error){
      const message=error instanceof Error?error.message:"发送失败";
      notify(error instanceof ApiError&&error.uncertain?message+" 请在会话中核对是否已创建，不要重复发送。":message);
    }finally{setBusy(false);}
  };
  return <section className="conversation" aria-label="对话工作区">
    {sessionId && loading&&!session?<div className="center-loading">正在载入会话…</div>:
      loadError&&!session?<div className="center-loading error"><strong>读取会话失败</strong><p>{loadError}</p><button onClick={()=>void refresh(sessionId)}>重试</button></div>:
      session&&session.messages.length?<Thread session={session}/>:
      <div className="chat-welcome"><div className="welcome-overline"><span className="mark-swatch"/> YOUR AGENT WORKSPACE</div>
        <h1>在这里，开始一段工作。</h1>
        <p>让 Myth 研究、执行并保留证据。每一步都可以查看、调整和恢复。</p>
        <div className="welcome-prompts">
          <button onClick={()=>{edit("请先分析当前任务的目标、约束与验收标准，再给出执行计划。");inputRef.current?.focus();}}><Target size={18}/>梳理任务 <ArrowUp size={14}/></button>
          <button onClick={()=>navigate("projects")}><Workflow size={18}/>打开项目 <ArrowUp size={14}/></button>
          <button onClick={()=>navigate("knowledge")}><BookOpen size={18}/>查阅资料 <ArrowUp size={14}/></button>
        </div>
      </div>
    }
    <div className="composer-zone">
      {latest&&["UNKNOWN","INTERRUPTED","PAUSED","WAITING_USER","FAILED","BUDGET_EXHAUSTED"].includes(latest.status)?
        <div className={"run-alert "+(["FAILED","BUDGET_EXHAUSTED"].includes(latest.status)?"error":"")}>
          <div><strong>{statusText(latest.status)}</strong><p>{latest.error||(
            latest.status==="UNKNOWN"?"执行结果尚不确定，核对后才能继续。":
            latest.status==="WAITING_USER"?"Agent 正在等待你的答复。":
            latest.status==="PAUSED"?"Run 已暂停，已派发调用的真实结果仍会保存。":
            latest.status==="INTERRUPTED"?"Driver 中断，已保存执行断点。":"请检查运行详情。"
          )}</p></div>
          {["UNKNOWN","INTERRUPTED"].includes(latest.status)?<button disabled={controlBusy} onClick={()=>void control("continue")}>核对并继续</button>:null}
        </div>:null}
      {latest&&busyRun?<div className="run-control-strip">
        <span className={"status-indicator state-"+latest.status.toLowerCase()}/><span>{statusText(latest.status)}</span>
        {latest.status==="RUNNING"&&!latest.control?.paused?<button disabled={controlBusy} onClick={()=>void control("pause")}><Pause size={14}/>暂停</button>:null}
        {latest.status==="PAUSED"?<button disabled={controlBusy} onClick={()=>void control("resume")}><Play size={14}/>恢复</button>:null}
        {latest.status==="RUNNING"?<button disabled={controlBusy} onClick={()=>void control("compact")}>Compact</button>:null}
        {!latest.control?.stopped?<button disabled={controlBusy} onClick={()=>setSteering(true)}><StepForward size={14}/>调整</button>:null}
        {!latest.control?.stopped&&!finalStatus.has(latest.status)?<button className="danger-action" disabled={controlBusy} onClick={()=>void control("stop")}><Square size={14}/>停止</button>:null}
      </div>:null}
      {docs.length?<div className="attachment-strip">{docs.map(id=><button key={id} onClick={()=>setDocs(x=>x.filter(d=>d!==id))}><FileText size={14}/>{bootstrap.documents.find(d=>d.id===id)?.title||id} ×</button>)}</div>:null}
      <form className="composer" onSubmit={e=>void send(e)}>
        <textarea ref={inputRef} value={text} disabled={busy||busyRun&&latest?.status!=="WAITING_USER"}
          placeholder={latest?.status==="WAITING_USER"?"回答 Agent 的问题…":"告诉 Myth 你想完成什么…"}
          aria-label="消息输入" rows={3}
          onChange={e=>edit(e.target.value)} onCompositionStart={()=>composing.current=true} onCompositionEnd={()=>composing.current=false}
          onKeyDown={e=>{if(e.key==="Enter"&&!e.shiftKey&&!e.nativeEvent.isComposing&&!composing.current){e.preventDefault();void send();}}}/>
        <div className="composer-footer">
          <div className="composer-tools">
            <button type="button" title="新对话" aria-label="新对话" onClick={()=>navigate("chat")}><MessageSquarePlus size={17}/></button>
            <button type="button" title="添加知识资料" aria-label="添加知识资料" onClick={()=>setAttachOpen(x=>!x)}><FileText size={17}/></button>
            <select aria-label="关联项目" value={session?.project_id||projectId} disabled={!!session} onChange={e=>setProjectId(e.target.value)}>
              <option value="">独立对话</option>{bootstrap.projects.map(p=><option value={p.id} key={p.id}>{p.name}</option>)}
            </select>
            <select aria-label="长期 Goal" value={goalId} disabled={busyRun} onChange={e=>setGoalId(e.target.value)}>
              <option value="">未关联 Goal</option>{bootstrap.goals.filter(g=>g.state!=="ARCHIVED").map(g=><option value={g.goal_id} key={g.goal_id}>{g.title}</option>)}
            </select>
          </div>
          <button className="send-action" type="submit" disabled={!canSend} title="Enter 发送 · Shift Enter 换行">{busy?"…":<Send size={17}/>}</button>
        </div>
      </form>
      {attachOpen?<div className="attachment-popover"><strong>从知识库添加</strong>
        {bootstrap.documents.filter(d=>!d.archived).length?bootstrap.documents.filter(d=>!d.archived).map(d=>
          <label key={d.id}><input type="checkbox" checked={docs.includes(d.id)} onChange={e=>setDocs(old=>e.target.checked?[...old,d.id]:old.filter(x=>x!==d.id))}/>{d.title}</label>):
          <p>暂无资料，请前往知识库导入。</p>}</div>:null}
      <div className="composer-caption">执行事实保留在 Runtime · Enter 发送 / Shift+Enter 换行</div>
    </div>
    {steering?<div className="modal-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget)setSteering(false);}}>
      <div className="dialog-card" role="dialog" aria-modal="true" aria-labelledby="steerTitle"><h2 id="steerTitle">调整当前 Run</h2>
        <p>指令只在下一个安全点生效，已派发动作仍保留真实收据。</p>
        <label>Steering<textarea value={steerText} onChange={e=>setSteerText(e.target.value)} rows={3}/></label>
        <button disabled={!steerText.trim()||controlBusy} onClick={async()=>{await control("steer",{text:steerText});setSteering(false);}}>应用 Steering</button>
        <label>下一步模型<input value={controlModel} placeholder={latest?.settings?.model} onChange={e=>setControlModel(e.target.value)}/></label>
        <button disabled={!controlModel.trim()||controlBusy} onClick={async()=>{await control("switch_model",{model:controlModel});setSteering(false);}}>切换模型</button>
        <label>Thinking<input value={controlThinking} placeholder={String(latest?.settings?.thinking??"default")} onChange={e=>setControlThinking(e.target.value)}/></label>
        <button disabled={!controlThinking.trim()||controlBusy} onClick={async()=>{await control("switch_thinking",{thinking:controlThinking});setSteering(false);}}>切换 Thinking</button>
        <button className="ghost-button" onClick={()=>setSteering(false)}>关闭</button>
      </div></div>:null}
  </section>;
}
