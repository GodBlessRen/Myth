import {FormEvent,useEffect,useState} from "react";
import {CheckCircle2,Cpu,KeyRound,Link2,ShieldCheck} from "lucide-react";
import {ModelPool,PricingEditor,poolProviders} from "./ModelPool";
import {auth,workspace} from "../api";
import {useRefresh} from "../workspace";
import {asRecord,displayValue} from "../types";
import type {Bootstrap,Settings,UnknownRecord} from "../types";

type Props={data:Bootstrap;notify:(message:string)=>void};
const providers=poolProviders;
const keyProviders=new Set(["openai","deepseek","anthropic","kimi"]);
function updateForm<K extends keyof Settings>(set:(f:(value:Settings)=>Settings)=>void,key:K,value:Settings[K]){
  set(old=>({...old,[key]:value}));
}
function AuthPanel({provider,notify}:{provider:string;notify:(message:string)=>void}){
  const [state,setState]=useState<UnknownRecord>({}),[secret,setSecret]=useState(""),[clientId,setClientId]=useState(""),[busy,setBusy]=useState(false);
  const check=async()=>{
    try{
      const namespace=provider==="chatgpt"?"chatgpt":provider==="claude_oauth"?"claude":"providers";
      setState(await auth.read<UnknownRecord>(namespace,"/status"));
    }catch(error){notify(error instanceof Error?error.message:"认证状态读取失败");}
  };
  useEffect(()=>{setState({});setSecret("");void check();
  // 当前 Provider 是认证状态所有权的唯一 UI 身份。
  // eslint-disable-next-line react-hooks/exhaustive-deps
  },[provider]);
  const run=async(callback:()=>Promise<void>)=>{setBusy(true);try{await callback();}catch(e){notify(e instanceof Error?e.message:"操作未完成");}finally{setBusy(false);}};
  const oauth=async()=>{
    // 用户点击时打开本机弹窗，返回结果不能通过 opener 操纵工作台。
    const popup=window.open("about:blank","myth-"+provider+"-oauth","width=640,height=760");
    try {
      const name=provider==="chatgpt"?"chatgpt":"claude";
      const attempt=await auth.post<{auth_url:string;login_id:string}>(name,"/start",provider==="chatgpt"?{profile_id:asRecord(state.status).profile_id||null}:{});
      if(!popup)throw new Error("浏览器阻止了登录弹窗");
      popup.opener=null;popup.location=attempt.auth_url;
      for(let i=0;i<150;i++){
        await new Promise(resolve=>window.setTimeout(resolve,1000));
        const now=await auth.read<{status:UnknownRecord}>(name,"/status");
        if(now.status?.login_revision===attempt.login_id){popup.close();setState(now);notify("认证状态已更新");return;}
        if(popup.closed&&i>2)break;
      }
      throw new Error("尚未检测到本次 OAuth 授权完成，请核对连接状态。");
    }catch(error){popup?.close();throw error;}
  };
  const status=asRecord(state.status);
  const keyStatuses=Array.isArray(state.providers)?state.providers.map(asRecord):[];
  const keyStatus=keyStatuses.find(s=>s.provider===provider);
  return <div className="panel auth-panel"><div className="panel-top"><ShieldCheck size={18}/><div><h2>身份与凭据</h2><p>凭据由 Myth Python 适配器保存，React 只读取脱敏状态。</p></div></div>
    {keyProviders.has(provider)?<>
      <p className="subtext">{keyStatus?.configured?`已连接 · ${displayValue(keyStatus.source)}`:"尚未连接 "+provider}</p>
      <label>API Key <input type="password" autoComplete="off" value={secret} onChange={e=>setSecret(e.target.value)} placeholder="粘贴后验证并保存到系统凭据库"/></label>
      <div className="button-row"><button className="solid-action" disabled={busy||!secret.trim()} onClick={()=>void run(async()=>{
        try{await auth.post("providers","/connect",{provider,api_key:secret});setSecret("");await check();notify("凭据验证并保存");}
        finally{setSecret("");}
      })}><KeyRound size={15}/>连接</button>
      <button disabled={busy||!keyStatus?.configured} onClick={()=>void run(async()=>{await auth.post("providers","/disconnect",{provider});await check();notify("凭据已断开");})}>断开</button></div>
    </>:provider==="chatgpt"||provider==="claude_oauth"?<>
      <p className="subtext">{status.connected?"已连接 · "+displayValue(status.email||status.name):"尚未连接"} · {displayValue(status.reason||"认证状态")}</p>
      {provider==="claude_oauth"&&!status.client_id_configured?<div className="stacked"><label>Myth OAuth Client ID（非 secret）<input value={clientId} onChange={e=>setClientId(e.target.value)} autoComplete="off"/></label>
        <button className="subtle-button" disabled={busy||!clientId.trim()} onClick={()=>void run(async()=>{await auth.post("claude","/configure",{client_id:clientId.trim()});setClientId("");await check();})}>保存 Client ID</button></div>:null}
      <div className="button-row"><button className="solid-action" disabled={busy||provider==="claude_oauth"&&!status.client_id_configured} onClick={()=>void run(oauth)}>
        <Link2 size={15}/>在浏览器中授权</button><button disabled={busy||!status.connected} onClick={()=>void run(async()=>{
          await auth.post(provider==="chatgpt"?"chatgpt":"claude","/logout",{});await check();notify("本地凭据已清理；如远端未撤销请在供应商端确认。");
        })}>退出</button></div>
    </>:<p className="subtext">本地 Ollama 不需要在此保存 API Key。</p>}
    <button className="ghost-button" disabled={busy} onClick={()=>void check()}>刷新认证状态</button>
  </div>;
}
export function SettingsPage({data,notify}:Props){
  const [form,setForm]=useState<Settings>(()=>({...data.settings}));
  const [pool,setPool]=useState<UnknownRecord>(()=>({...asRecord(data.settings.model_pool)}));
  const [busy,setBusy]=useState(false);
  const [connection,setConnection]=useState<UnknownRecord|null>(null);
  const [connectionBusy,setConnectionBusy]=useState(false);
  const refresh=useRefresh();
  const details=asRecord(connection?.details), capabilities=asRecord(details.model_capabilities),profile=asRecord(capabilities[form.model]);
  const reasoning=asRecord(profile.reasoning),levels=Array.isArray(reasoning.levels)?reasoning.levels.map(String):[];
  const models=Array.isArray(details.models)?details.models.map(String):[];
  const changeProvider=(value:string)=>{
    setConnection(null);
    setForm(old=>({...old,provider:value,model:"",thinking:null}));
  };
  const save=async(e:FormEvent)=>{
    e.preventDefault();setBusy(true);
    try{const actual=await workspace.settings({...form,model_pool:pool});setForm(actual);setPool(asRecord(actual.model_pool));await refresh();notify("设置已提交并保存");}
    catch(error){notify(error instanceof Error?error.message:"设置保存失败");}finally{setBusy(false);}
  };
  const check=async()=>{
    setConnectionBusy(true);
    try{const result=await workspace.post<UnknownRecord>("/connection",form);setConnection(result);notify(result.ready?"Provider 已连接":"Provider 未就绪，请检查配置");}
    catch(error){notify(error instanceof Error?error.message:"连接检查失败");}finally{setConnectionBusy(false);}
  };
  return <section className="content-page">
    <header className="page-header"><div><span className="micro-label">MYTH / CONFIGURATION</span><h1>模型与连接</h1><p>选择模型、配置推理能力和子模型池。更改不修改正在运行的历史调用。</p></div>
      <button type="submit" form="modelSettingsForm" className="solid-action" disabled={busy}>{busy?"保存中…":"保存设置"}</button>
    </header>
    <div className="settings-grid"><div className="settings-stack">
      <form id="modelSettingsForm" className="panel" onSubmit={e=>void save(e)}>
        <div className="panel-top"><Cpu size={18}/><div><h2>主模型</h2><p>模型能力来自供应商目录，不按品牌推断支持范围。</p></div></div>
        <div className="form-grid"><label>Provider<select value={form.provider||"ollama"} onChange={e=>changeProvider(e.target.value)}>
          {providers.map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>
          <label>模型<input list="models" required value={form.model||""} onChange={e=>updateForm(setForm,"model",e.target.value)} placeholder="选择或输入模型名称"/><datalist id="models">{models.map(m=><option key={m} value={m}/>)}</datalist></label>
          {form.provider==="ollama"?<>
            <label>Ollama 地址<input value={form.ollama_url||"http://127.0.0.1:11434"} onChange={e=>updateForm(setForm,"ollama_url",e.target.value)}/></label>
            <label>上下文 Tokens<input type="number" min={2048} max={262144} value={form.num_ctx??8192} onChange={e=>updateForm(setForm,"num_ctx",Number(e.target.value))}/></label>
          </>:null}
          <label>最大步骤<input type="number" min={2} max={32} value={form.max_steps??12} onChange={e=>updateForm(setForm,"max_steps",Number(e.target.value))}/></label>
          <label>初始输出 Token<input title="达到长度上限后，可在整轮预算与窗口内增大一次；GPT OAuth 由远端控制。" type="number" min={128} max={393216} value={form.max_output_tokens??8192} onChange={e=>updateForm(setForm,"max_output_tokens",Number(e.target.value))}/></label>
          {profile.temperature!==undefined||form.provider==="ollama"?<label>Temperature<input type="number" min={0} max={2} step={0.1} value={form.temperature??0} onChange={e=>updateForm(setForm,"temperature",Number(e.target.value))}/></label>:null}
          {levels.length?<label>Thinking<select value={String(form.thinking??"default")} onChange={e=>updateForm(setForm,"thinking",e.target.value==="default"?null:e.target.value)}>
            <option value="default">默认</option><option value="none">关闭</option>{levels.map(l=><option value={l} key={l}>{l}</option>)}</select></label>:
            <label>Thinking 状态<input disabled value={displayValue(form.thinking??"模型默认")} title="当前目录未报告可调档位"/></label>}
        </div>
        <div className="button-row"><button type="button" disabled={connectionBusy} className="subtle-button" onClick={()=>void check()}><Link2 size={15}/>{connectionBusy?"检查中…":"检查模型连接"}</button>
          {connection?<span className="connection-result"><CheckCircle2 size={15}/>{connection.ready?"连接可用":"连接不可用"}</span>:null}
        </div>
        <button type="submit" className="solid-action" disabled={busy||!form.model.trim()}>保存模型配置</button>
      </form>
      <PricingEditor provider={form.provider} model={form.model} value={pool.main_pricing} notify={notify} onChange={value=>setPool(old=>({...old,main_pricing:value}))}/>
      <ModelPool pool={pool} setPool={setPool} notify={notify}/>
    </div>
    <AuthPanel key={form.provider} provider={form.provider||"ollama"} notify={notify}/></div>
  </section>;
}
