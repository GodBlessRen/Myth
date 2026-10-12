import {useEffect,useMemo,useState} from "react";
import {Activity,BookOpen,ChevronDown,Command,Folder,History,LayoutPanelLeft,Menu,Moon,PanelLeftClose,PanelRightClose,Plus,Search,Settings,Sun,Target,TextQuote,X} from "lucide-react";
import {useUi} from "./store";
import {beginNewChat,navigate,useBootstrap,useRoute,useSession} from "./workspace";
import {asRecord,displayValue,statusText} from "./types";
import {Chat} from "./components/Chat";
import {Observatory} from "./components/Observatory";
import {Sessions,Projects,Knowledge} from "./components/Management";
import {Goals} from "./components/Goals";
import {SettingsPage} from "./components/Settings";
import {useDialogAccessibility} from "./components/useDialogAccessibility";

const primary=[
  {page:"chat",label:"对话",icon:TextQuote},
  {page:"goals",label:"目标与计划",icon:Target},
  {page:"projects",label:"项目",icon:Folder},
  {page:"knowledge",label:"知识库",icon:BookOpen},
  {page:"sessions",label:"会话",icon:History},
  {page:"runtime",label:"Runtime",icon:Activity},
  {page:"settings",label:"设置",icon:Settings},
] as const;
function RuntimePage({platform,runs}:{platform:unknown;runs:unknown}){
  const items=Array.isArray(runs)?runs.map(asRecord):[];
  return <section className="content-page"><header className="page-header"><div><span className="micro-label">MYTH / DURABLE RUNTIME</span><h1>Runtime</h1><p>运行能力、恢复状态及已保存执行事实，不受页面重建影响。</p></div></header>
    <div className="panels-grid"><article className="panel"><h2>可恢复 Run</h2>{items.length?items.map((r,i)=><button className="text-row" key={String(r.run_id||i)} onClick={()=>r.session_id&&navigate("chat",String(r.session_id))}>
      <span><strong>{statusText(String(r.status||""))}</strong><small>{displayValue(r.run_id)}</small></span><span>查看会话 →</span></button>):<p className="subtext">暂无可恢复 Run</p>}</article>
    <article className="panel"><h2>平台能力</h2><p className="subtext">状态由后端提供，未测量的能力不显示为已就绪。</p><pre className="evidence-raw">{JSON.stringify(platform||{},null,2)}</pre></article></div>
  </section>;
}
function ConnectionNotice({onRetry,message}:{onRetry:()=>void;message:string}){
  return <div className="load-failure"><Activity size={28}/><h1>无法读取工作空间</h1><p>{message}</p>
    <button className="solid-action" onClick={onRetry}>重新连接</button><a href="/" className="subtle-button">返回旧版工作台</a></div>;
}
export function App(){
  useDialogAccessibility();
  const {page,id}=useRoute();
  const {sidebar,setSidebar,inspector,setInspector,theme,toggleTheme,density,toggleDensity,commandOpen,setCommandOpen}=useUi();
  const bootstrap=useBootstrap();
  const sessionQuery=useSession(page==="chat"?id:null);
  const data=bootstrap.data;
  const session=page==="chat"?sessionQuery.data||null:null;
  const turn=session?.turns.at(-1);
  const [notice,setNotice]=useState(""),[commandText,setCommandText]=useState("");
  const notify=(message:string)=>setNotice(message);
  const currentTitle=useMemo(()=>{
    if(page==="chat"&&session)return session.title;
    if(page==="projects"&&id)return data?.projects.find(p=>p.id===id)?.name||"项目";
    return primary.find(x=>x.page===page)?.label||"Myth";
  },[page,id,session,data]);
  const commands=useMemo(()=>{
    const pages=primary.map(p=>({id:p.page,label:p.label,href:p.page}));
    const sessions=(data?.sessions||[]).map(s=>({id:s.id,label:s.title,href:"chat/"+s.id}));
    return [...pages,...sessions].filter(p=>p.label.toLowerCase().includes(commandText.toLowerCase())).slice(0,18);
  },[data,commandText]);
  useEffect(()=>{
    document.documentElement.dataset.theme=theme;
    document.documentElement.dataset.density=density;
    document.documentElement.style.colorScheme=theme;
  },[theme,density]);
  useEffect(()=>{
    if(!notice)return;
    const timer=window.setTimeout(()=>setNotice(""),6500);
    return ()=>window.clearTimeout(timer);
  },[notice]);
  useEffect(()=>{
    const shortcut=(e:KeyboardEvent)=>{
      if(e.isComposing||e.keyCode===229)return;
      if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="k"){e.preventDefault();setCommandOpen(!commandOpen);}
      else if((e.ctrlKey||e.metaKey)&&e.shiftKey&&e.key.toLowerCase()==="o"){e.preventDefault();beginNewChat();}
      else if(e.key==="Escape"){
        if(document.querySelector('[role="dialog"][aria-modal="true"]'))return;
        if(commandOpen)setCommandOpen(false);
        else if(window.innerWidth<=1120&&inspector)setInspector(false);
        else if(window.innerWidth<=800&&sidebar)setSidebar(false);
      }
    };
    document.addEventListener("keydown",shortcut);
    return ()=>document.removeEventListener("keydown",shortcut);
  },[commandOpen,setCommandOpen,inspector,setInspector,sidebar,setSidebar]);
  // React 是独立页面的唯一 DOM owner；Python 响应是唯一持久状态来源。
  if(bootstrap.isLoading&&!data)return <div className="boot-loading"><div className="brand-monogram">M</div><p>正在连接 Myth 工作空间…</p></div>;
  if(!data)return <ConnectionNotice onRetry={()=>void bootstrap.refetch()} message={bootstrap.error instanceof Error?bootstrap.error.message:"本地 Python 服务未响应"}/>;
  const nav=(target:string,id?:string)=>{navigate(target,id);if(window.innerWidth<=800)setSidebar(false);};
  const fresh=()=>{beginNewChat();if(window.innerWidth<=800)setSidebar(false);};
  return <div className={"app-shell "+(!sidebar?"sidebar-closed ":"")+(!inspector?"inspector-closed":"")}>
    {sidebar?<button className="sidebar-screen" aria-label="关闭导航" onClick={()=>setSidebar(false)}/>:null}
    {sidebar?<aside className="sidebar" aria-label="主导航">
      <header className="sidebar-head"><button className="brand" onClick={fresh} aria-label="Myth 新对话">
        <img src={theme==="dark"?"/logo-dark.svg":"/logo.svg"} alt=""/><strong>Myth</strong><small>WORKBENCH</small></button>
        <button className="icon-action" onClick={()=>setSidebar(false)} aria-label="收起导航"><PanelLeftClose size={18}/></button>
      </header>
      <button className="new-conversation" onClick={fresh}><Plus size={18}/>新建对话 <kbd>Ctrl ⇧ O</kbd></button>
      <button className="command-entry" onClick={()=>{setCommandOpen(true);setCommandText("");}}><Search size={16}/>搜索与快捷操作 <kbd>Ctrl K</kbd></button>
      <div className="sidebar-scroll"><p className="nav-caption">WORKSPACE</p>
        <nav className="nav-items">{primary.slice(0,5).map(item=><button key={item.page} aria-current={page===item.page?"page":undefined}
          onClick={()=>nav(item.page)} className={page===item.page?"selected":""}><item.icon size={17}/>{item.label}</button>)}</nav>
        <p className="nav-caption">RECENT SESSIONS</p>
        <nav className="recent-items">{data.sessions.slice(0,12).map(s=><button key={s.id} title={s.title}
          onClick={()=>nav("chat",s.id)} className={page==="chat"&&id===s.id?"selected":""}>{s.pinned?"◈ ":""}{s.title}</button>)}
          {!data.sessions.length?<span>暂无会话</span>:null}</nav>
      </div>
      <div className="sidebar-foot">
        <button onClick={()=>nav("runtime")} className={page==="runtime"?"selected":""}><Activity size={17}/>Runtime</button>
        <button onClick={()=>nav("settings")} className={page==="settings"?"selected":""}><Settings size={17}/>设置</button>
        <div className="workspace-identity"><span className="workspace-symbol">M</span><div><strong>个人工作区</strong><small>Local first · Python Runtime</small></div></div>
      </div>
    </aside>:null}
    {!sidebar?<button className="sidebar-rail" onClick={()=>setSidebar(true)} aria-label="展开导航"><LayoutPanelLeft size={19}/></button>:null}
    <div className="primary-stage">
      <header className="topbar">
        <div className="topbar-title"><button className="icon-action mobile-nav" onClick={()=>setSidebar(true)} aria-label="打开导航"><Menu size={19}/></button>
          <span>工作空间</span><ChevronDown size={13}/><strong>{currentTitle}</strong></div>
        <div className="topbar-tools">
          <button className="header-status" onClick={()=>{setInspector(true);}} title="查看 Runtime 真实状态"><span className={"status-indicator state-"+(turn?.status||"IDLE").toLowerCase()}/>{statusText(turn?.status)}</button>
          <button className="top-model" onClick={()=>nav("settings")}><span className="model-signal"/><span title={data.settings.model}>{data.settings.model||"选择模型"}</span><ChevronDown size={14}/></button>
          <button className="icon-action optional-control" onClick={toggleDensity} title="切换阅读密度" aria-label="切换阅读密度"><TextQuote size={17}/></button>
          <button className="icon-action" onClick={toggleTheme} aria-label={theme==="light"?"切换到深色":"切换到浅色"}>{theme==="light"?<Moon size={17}/>:<Sun size={17}/>}</button>
          <button className="icon-action inspector-control" onClick={()=>setInspector(!inspector)} aria-label={inspector?"收起运行观测":"展开运行观测"}><PanelRightClose size={18}/></button>
        </div>
      </header>
      <main className="main-content" key={page==="settings"?"settings":undefined}>
        {page==="chat"?<Chat bootstrap={data} session={session} sessionId={id} loading={sessionQuery.isLoading}
          loadError={sessionQuery.error instanceof Error?sessionQuery.error.message:undefined} notify={notify}/>:null}
        {page==="sessions"?<Sessions data={data} notify={notify}/>:null}
        {page==="projects"?<Projects data={data} id={id} notify={notify}/>:null}
        {page==="knowledge"?<Knowledge data={data} notify={notify}/>:null}
        {page==="goals"?<Goals data={data} notify={notify}/>:null}
        {page==="runtime"?<RuntimePage platform={data.platform} runs={data.recoverable_runs}/>:null}
        {page==="settings"?<SettingsPage data={data} notify={notify}/>:null}
      </main>
    </div>
    {inspector?<button className="inspector-screen" aria-label="关闭运行观测" onClick={()=>setInspector(false)}/>:null}
    <Observatory session={session}/>
    {commandOpen?<div className="palette-mask" onMouseDown={e=>{if(e.target===e.currentTarget)setCommandOpen(false);}}>
      <div className="command-palette" role="dialog" aria-modal="true" aria-label="搜索与快捷操作">
        <div className="palette-input"><Command size={19}/><input autoFocus value={commandText} onChange={e=>setCommandText(e.target.value)} placeholder="搜索页面与会话…" onKeyDown={e=>{
          if(e.key==="Enter"&&commands[0]){navigate(...(commands[0].href.split("/") as [string,string?]));setCommandOpen(false);}
        }}/><button className="icon-action" data-dialog-close aria-label="关闭搜索" onClick={()=>setCommandOpen(false)}><X size={17}/></button></div>
        <div className="palette-items">{commands.length?commands.map(c=><button key={c.href} onClick={()=>{const [p,...parts]=c.href.split("/");navigate(p,parts.join("/")||undefined);setCommandOpen(false);}}><Search size={15}/>{c.label}</button>):<p>没有匹配结果</p>}</div>
        <footer>Enter 打开 · Esc 关闭</footer>
      </div>
    </div>:null}
    {notice?<div className="toast-message" role="status">{notice}<button aria-label="关闭提示" onClick={()=>setNotice("")}><X size={15}/></button></div>:null}
    {bootstrap.isError&&data?<div className="connection-warning" role="status">工作区断连，保留最近读取的投影；正在重连。</div>:null}
  </div>;
}
