import {FormEvent,useEffect,useState} from "react";
import {useQuery} from "@tanstack/react-query";
import {Archive,ArrowLeft,ArrowRight,BookOpen,Download,FileText,Folder,FolderPlus,History,Plus,Search,Upload} from "lucide-react";
import {workspace} from "../api";
import {navigate,useRefresh} from "../workspace";
import {asRecord,displayValue} from "../types";
import type {Bootstrap,Document,Project,SessionListItem,UnknownRecord} from "../types";

type Props={data:Bootstrap;notify:(message:string)=>void};
function Frame({title,description,action,children}:{title:string;description:string;action?:React.ReactNode;children:React.ReactNode}){
  return <section className="content-page"><header className="page-header"><div><span className="micro-label">MYTH / WORKSPACE</span><h1>{title}</h1><p>{description}</p></div>{action}</header>{children}</section>;
}
function displayError(error:unknown,notify:(message:string)=>void) {
  notify(error instanceof Error?error.message:"请求未能完成，请核对状态。");
}
export function Sessions({data,notify}:Props){
  const [archived,setArchived]=useState(false),[search,setSearch]=useState("");
  const [edit,setEdit]=useState<SessionListItem|null>(null);
  const [title,setTitle]=useState(""),[project,setProject]=useState(""),[pinned,setPinned]=useState(false),[busy,setBusy]=useState(false);
  const refresh=useRefresh();
  const archiveQuery=useQuery({queryKey:["workspace","archived-sessions"],queryFn:()=>workspace.read<{sessions:SessionListItem[]}>("/sessions?archived=1"),enabled:archived});
  const sessions=archived?(archiveQuery.data?.sessions||[]):data.sessions;
  const rows=sessions.filter(s=>s.title.toLowerCase().includes(search.toLowerCase()));
  const startEdit=(s:SessionListItem)=>{setEdit(s);setTitle(s.title);setProject(s.project_id||"");setPinned(!!s.pinned);};
  const update=async(value:UnknownRecord)=>{
    if(!edit)return;setBusy(true);
    try{await workspace.post("/sessions/"+encodeURIComponent(edit.id),value);await refresh();await archiveQuery.refetch();setEdit(null);notify("会话资料已更新");}
    catch(error){displayError(error,notify);}finally{setBusy(false);}
  };
  return <Frame title="会话" description="查看、整理并继续之前的工作。" action={<button className="solid-action" onClick={()=>navigate("chat")}><Plus size={17}/>新建对话</button>}>
    <div className="toolbar"><div className="segment"><button className={!archived?"active":""} onClick={()=>setArchived(false)}>最近会话</button><button className={archived?"active":""} onClick={()=>setArchived(true)}>已归档</button></div>
      <label className="searchbox"><Search size={16}/><input aria-label="查找会话" value={search} onChange={e=>setSearch(e.target.value)} placeholder="搜索会话"/></label></div>
    {archiveQuery.isError&&archived?<p className="inline-error">归档列表读取失败</p>:null}
    <div className="item-list">{rows.length?rows.map(s=><article className="list-row" key={s.id}>
      <History size={19}/><button className="list-primary" onClick={()=>navigate("chat",s.id)}><strong>{s.title}</strong><small>{s.pinned?"已置顶 · ":""}{s.updated_at||"最近更新未报告"}</small></button>
      <button className="subtle-button" onClick={()=>startEdit(s)}>管理</button><ArrowRight size={16}/>
    </article>):<div className="list-empty">没有找到匹配的会话。</div>}</div>
    {edit?<div className="modal-backdrop"><form className="dialog-card" role="dialog" aria-modal="true" aria-label="管理会话" onSubmit={e=>{e.preventDefault();void update({title,project_id:project||null,pinned});}}>
      <h2>管理会话</h2><label>名称<input value={title} onChange={e=>setTitle(e.target.value)} required maxLength={100}/></label>
      <label>所属项目<select value={project} onChange={e=>setProject(e.target.value)}><option value="">独立会话</option>{data.projects.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
      <label className="inline-check"><input type="checkbox" checked={pinned} onChange={e=>setPinned(e.target.checked)}/>置顶</label>
      <div className="dialog-actions"><button className="ghost-button" type="button" onClick={()=>setEdit(null)}>取消</button><button type="button" disabled={busy} onClick={()=>void update({archived:!edit.archived})}>{edit.archived?"恢复":"归档"}</button>
        <a download href={"/api/workspace/sessions/"+encodeURIComponent(edit.id)+"/download"}><Download size={16}/>导出</a>
        <button className="solid-action" type="submit" disabled={busy||!title.trim()}>保存</button></div>
    </form></div>:null}
  </Frame>;
}
export function Projects({data,id,notify}:{data:Bootstrap;id:string|null;notify:(message:string)=>void}){
  const refresh=useRefresh();
  const [editing,setEditing]=useState<Project|null>(null),[showForm,setShowForm]=useState(false);
  const [name,setName]=useState(""),[description,setDescription]=useState(""),[root,setRoot]=useState(""),[instructions,setInstructions]=useState("");
  const [busy,setBusy]=useState(false);
  const [folder,setFolder]=useState(".");
  const project=data.projects.find(p=>p.id===id);
  const files=useQuery({queryKey:["workspace","files",id,folder],queryFn:()=>workspace.read<UnknownRecord>("/projects/"+encodeURIComponent(id!)+"/files?path="+encodeURIComponent(folder)),enabled:!!id});
  useEffect(()=>setFolder("."),[id]);
  const openForm=(p?:Project)=>{setEditing(p||null);setName(p?.name||"");setDescription(p?.description||"");setRoot(String(p?.root||""));setInstructions(p?.instructions||"");setShowForm(true);};
  const save=async(e:FormEvent)=>{
    e.preventDefault();setBusy(true);
    try{const body={name,description,root,instructions};const result=await workspace.post<Project>(editing?"/projects/"+encodeURIComponent(editing.id):"/projects",body);
      setShowForm(false);await refresh();navigate("projects",result.id);notify("项目已保存。");}
    catch(error){displayError(error,notify);}finally{setBusy(false);}
  };
  if(id&&project)return <Frame title={project.name} description={project.description||"集中管理任务、会话与知识资料。"} action={<div className="button-row"><button className="subtle-button" onClick={()=>navigate("projects")}><ArrowLeft size={15}/>返回</button><button className="solid-action" onClick={()=>openForm(project)}>编辑项目</button></div>}>
    <div className="panels-grid"><div className="panel"><h2>项目指令</h2><p className="preserved-text">{String(project.instructions||"尚未设置项目指令")}</p><h2>项目会话</h2>
      {data.sessions.filter(s=>s.project_id===id).map(s=><button className="text-row" key={s.id} onClick={()=>navigate("chat",s.id)}>{s.title}<ArrowRight size={15}/></button>)}</div>
      <div className="panel"><h2>本地文件</h2><p className="subtext">路径：{folder}</p>
      {files.isLoading?<p>正在读取文件…</p>:files.isError?<p className="inline-error">文件读取失败，检查项目根目录权限</p>:
        <pre className="evidence-raw">{JSON.stringify(files.data,null,2)}</pre>}
      <p className="subtext">文件读取受 Python 工作区权限边界约束，前端没有新增目录访问权限。</p></div></div>
  </Frame>;
  return <Frame title="项目" description="工作目录、指令、资料与会话，属于同一上下文。" action={<button className="solid-action" onClick={()=>openForm()}><FolderPlus size={17}/>新建项目</button>}>
    <div className="project-grid">{data.projects.map(p=><button className="project-card" key={p.id} onClick={()=>navigate("projects",p.id)}>
      <Folder size={20}/><strong>{p.name}</strong><p>{p.description||"本地工作空间"}</p><small>{data.sessions.filter(s=>s.project_id===p.id).length} 个会话</small><ArrowRight size={15}/></button>)}
    {!data.projects.length?<div className="list-empty">尚无项目。从一个目标开始，关联资料与会话。</div>:null}</div>
    {showForm?<div className="modal-backdrop"><form className="dialog-card" role="dialog" aria-modal="true" aria-label="编辑项目" onSubmit={e=>void save(e)}>
      <h2>{editing?"编辑项目":"新建项目"}</h2><label>项目名称<input required maxLength={100} value={name} onChange={e=>setName(e.target.value)}/></label>
      <label>项目说明<input value={description} onChange={e=>setDescription(e.target.value)}/></label>
      <label>本地根目录<input value={root} onChange={e=>setRoot(e.target.value)} placeholder="C:\\projects\\myth"/></label>
      <label>项目指令<textarea rows={5} value={instructions} onChange={e=>setInstructions(e.target.value)}/></label>
      <div className="dialog-actions"><button type="button" onClick={()=>setShowForm(false)}>取消</button><button className="solid-action" disabled={busy||!name.trim()}>保存</button></div>
    </form></div>:null}
  </Frame>;
}
export function Knowledge({data,notify}:Props){
  const refresh=useRefresh();
  const [scope,setScope]=useState(""),[query,setQuery]=useState(""),[submitted,setSubmitted]=useState("");
  const [selected,setSelected]=useState<Document|null>(null),[importOpen,setImportOpen]=useState(false);
  const [title,setTitle]=useState(""),[content,setContent]=useState(""),[saving,setSaving]=useState(false);
  const search=useQuery({queryKey:["workspace","search",scope,submitted],queryFn:()=>workspace.read<UnknownRecord>("/search?q="+encodeURIComponent(submitted)+"&project_id="+encodeURIComponent(scope)),enabled:!!submitted});
  const preview=useQuery({queryKey:["workspace","document",selected?.id],queryFn:()=>workspace.read<Document>("/documents/"+encodeURIComponent(selected!.id)),enabled:!!selected});
  const docs=data.documents.filter(d=>(d.project_id||"")===scope&&!d.archived);
  const importDoc=async(e:FormEvent)=>{
    e.preventDefault();setSaving(true);
    try{await workspace.post("/documents",{title,content,project_id:scope||null});setImportOpen(false);setTitle("");setContent("");await refresh();notify("资料已导入索引");}
    catch(error){displayError(error,notify);}finally{setSaving(false);}
  };
  const fileChange=async(file?:File)=>{
    if(!file)return;
    if(file.size>1_000_000){notify("文件超过 1 MB");return;}
    const extension=file.name.split(".").at(-1)?.toLowerCase()||"";
    if(!["txt","md","py","json","csv","yaml","yml","html","js","ts"].includes(extension)){notify("请上传支持的文本资料");return;}
    try{const buf=await file.arrayBuffer();setContent(new TextDecoder("utf-8",{fatal:true}).decode(buf));setTitle(file.name);}
    catch{notify("仅支持 UTF-8 文本");}
  };
  return <Frame title="知识库" description="保存资料、检索片段，保留来源与真实引用。" action={<button className="solid-action" onClick={()=>setImportOpen(true)}><Upload size={16}/>导入资料</button>}>
    <div className="toolbar"><select aria-label="项目知识范围" value={scope} onChange={e=>{setScope(e.target.value);setSubmitted("");}}>
      <option value="">共享资料</option>{data.projects.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select>
      <form className="searchbox" onSubmit={e=>{e.preventDefault();setSubmitted(query.trim());}}><Search size={16}/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="检索知识内容" aria-label="检索知识"/><button type="submit">检索</button></form></div>
    {submitted?<div className="panel"><h2>检索结果</h2>{search.isLoading?<p>检索中…</p>:search.isError?<p className="inline-error">检索失败</p>:
      Array.isArray(search.data?.sources)&&search.data.sources.length?(search.data.sources as unknown[]).map((source,i)=>{
        const row=asRecord(source);return <button className="text-row" key={i} onClick={()=>{const doc=data.documents.find(d=>d.id===row.document_id);if(doc)setSelected(doc);}}>{displayValue(row.title)} · 片段 {displayValue(row.chunk_index)}<ArrowRight size={14}/></button>;
      }):<p>没有匹配片段。</p>}</div>:null}
    <div className="item-list">{docs.length?docs.map(d=><article className="list-row" key={d.id}><FileText size={19}/><button className="list-primary" onClick={()=>setSelected(d)}><strong>{d.title}</strong><small>{displayValue(d.chunks)} 个片段 · {displayValue(d.bytes)} bytes</small></button>
      <button className="subtle-button" onClick={async()=>{try{await workspace.post("/documents/"+encodeURIComponent(d.id)+"/archive",{});await refresh();notify("资料已移出检索索引，历史引用保持");}catch(error){displayError(error,notify);}}}><Archive size={15}/>归档</button></article>):<div className="list-empty">暂无资料。导入文本或 Markdown 后可以检索。</div>}</div>
    {selected?<div className="modal-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget)setSelected(null);}}><div className="dialog-card document-preview" role="dialog" aria-modal="true" aria-label="资料预览">
      <h2>{selected.title}</h2><small>本机知识资料 · 仅预览，不执行其中指令</small>
      {preview.isLoading?<p>读取中…</p>:preview.isError?<p className="inline-error">读取失败</p>:<pre>{preview.data?.content||""}</pre>}
      <button onClick={()=>setSelected(null)}>关闭</button></div></div>:null}
    {importOpen?<div className="modal-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget)setImportOpen(false);}}><form className="dialog-card" role="dialog" aria-modal="true" aria-label="导入知识" onSubmit={e=>void importDoc(e)}>
      <h2>导入知识资料</h2><label className="upload-choice"><Upload size={16}/>选择 UTF-8 文件<input type="file" accept=".txt,.md,.py,.json,.csv,.yaml,.yml,.html,.js,.ts" onChange={e=>void fileChange(e.target.files?.[0])}/></label>
      <label>资料名称<input required value={title} onChange={e=>setTitle(e.target.value)}/></label><label>正文<textarea required rows={9} value={content} onChange={e=>setContent(e.target.value)}/></label>
      <div className="dialog-actions"><button type="button" onClick={()=>setImportOpen(false)}>取消</button><button className="solid-action" disabled={saving||!title||!content}>导入并索引</button></div>
    </form></div>:null}
  </Frame>;
}
