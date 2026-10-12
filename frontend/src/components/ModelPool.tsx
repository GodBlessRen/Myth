import {useEffect,useRef,useState} from "react";
import {ChevronDown,Cpu,Link2,Plus,Trash2} from "lucide-react";
import {workspace} from "../api";
import {asRecord,displayValue} from "../types";
import type {UnknownRecord} from "../types";

// 模型池是 Turn 的公开配置草稿；密钥、执行事实和费用账本仍归 Python Runtime。
export const poolProviders = [
  ["ollama","Ollama 本地"],["openai","OpenAI API"],["deepseek","DeepSeek"],
  ["anthropic","Anthropic API"],["claude_oauth","Claude OAuth"],["kimi","Kimi"],["chatgpt","ChatGPT OAuth"]
] as const;
export const taskKinds = [
  ["general","通用"],["extract","抽取"],["summarize","摘要"],
  ["code","代码"],["reason","推理"],["review","审查"]
] as const;
type Props={pool:UnknownRecord;setPool:(value:UnknownRecord)=>void;notify:(message:string)=>void};
type PriceProps={provider:string;model:string;value:unknown;onChange:(value:unknown)=>void;notify:(message:string)=>void};
type Quote={status:string;provider?:string;model?:string;pricing:UnknownRecord|null;checked_at?:string;stale?:boolean;official_url?:string;max_output_tokens?:number};
const quotedText:Record<string,string>={
  unknown:"目录未收录此型号",unavailable:"目录暂不可用，费用未知",
  unpublished:"官方标价未公布",subscription:"订阅渠道，不套用 API 价格",
  oauth_channel:"OAuth 渠道，费用依供应商实际记录",
  local_or_hosted:"本地或自托管，不假设免费",unselected:"尚未选择型号"
};
const valueText=(value:unknown)=>typeof value==="string"?value:"";
const numberOr=(value:unknown,fallback:number)=>typeof value==="number"&&Number.isFinite(value)?value:fallback;
const choiceValue=(value:unknown)=>value==null?"default":value===true?"__on__":value===false?"__off__":String(value);
const nativeThinking=(value:string):string|boolean|null=>
  value==="default"?null:value==="__on__"?true:value==="__off__"?false:value;

export function PricingEditor({provider,model,value,onChange,notify}:PriceProps){
  const rates=asRecord(value),isManual=!!value&&!rates.source;
  const [quote,setQuote]=useState<Quote|null>(null),[loading,setLoading]=useState(false);
  const identity=provider+"|"+model.trim();
  const generation=useRef(0);
  useEffect(()=>{generation.current++;setQuote(null);setLoading(false);},[identity]);
  const lookup=async()=>{
    if(!model.trim())return;
    const attempt=++generation.current;setLoading(true);
    try{
      const result=await workspace.post<Quote>("/model-info",{provider,model:model.trim(),force:true});
      if(generation.current!==attempt||result.provider!==undefined&&result.provider!==provider||
          result.model!==undefined&&result.model!==model.trim())return;
      setQuote(result);
      if(!isManual)onChange(result.pricing??null);
    }catch(e){if(generation.current===attempt)notify(e instanceof Error?e.message:"价格查询失败");}
    finally{if(generation.current===attempt)setLoading(false);}
  };
  const update=(key:"input"|"output"|"currency",raw:string)=>{
    const next={currency:rates.currency==="CNY"?"CNY":"USD",
      input:rates.input??null,output:rates.output??null};
    onChange({...next,[key]:key==="currency"?raw:raw===""?null:Number(raw)});
  };
  return <div className="pricing-editor">
    <div className="button-row"><strong>计价 · 每百万 Token</strong>
      <button type="button" className="subtle-button" disabled={loading||!model.trim()} onClick={()=>void lookup()}>
        {loading?"查询中…":"查询公开标价"}</button></div>
    <p className="subtext" role="status">{isManual?"使用自定义费率":
      quote?.pricing?"输入 "+displayValue(quote.pricing.input)+" / 输出 "+displayValue(quote.pricing.output)+" USD":
      quote?quotedText[quote.status]||"费用未知":
      rates.source?"缓存标价 · "+displayValue(rates.source):"未报价，不将费用计为 0"}
      {quote?.stale?" · 缓存可能过期":""}</p>
    {quote?.official_url?<a href={quote.official_url} target="_blank" rel="noopener noreferrer">供应商定价说明 ↗</a>:null}
    {quote?.max_output_tokens?<small className="subtext">目录输出上限：{quote.max_output_tokens} Token</small>:null}
    <label className="inline-check"><input type="checkbox" checked={isManual} onChange={e=>{
      if(e.target.checked)onChange({currency:"USD",input:null,output:null});
      else onChange(quote?.pricing??null);
    }}/>自定义合同单价（关闭时使用公开报价或保持未知）</label>
    {isManual?<div className="form-grid">
      <label>币种<select value={valueText(rates.currency)||"USD"} onChange={e=>update("currency",e.target.value)}>
        <option value="USD">USD</option><option value="CNY">CNY</option></select></label>
      <label>输入单价<input type="number" min={0} max={100000} step="any" value={rates.input??""} onChange={e=>update("input",e.target.value)}/></label>
      <label>输出单价<input type="number" min={0} max={100000} step="any" value={rates.output??""} onChange={e=>update("output",e.target.value)}/></label>
      {(rates.input==null||rates.output==null)?<small className="subtext">两项单价须同时填写；不完整时服务端拒绝保存。</small>:null}
    </div>:null}
  </div>;
}

function ChildEditor({child,index,update,remove,notify}:{child:UnknownRecord;index:number;
  update:(key:string,value:unknown)=>void;remove:()=>void;notify:(message:string)=>void}){
  const provider=valueText(child.provider)||"ollama",model=valueText(child.model);
  const [connection,setConnection]=useState<UnknownRecord|null>(null),[checking,setChecking]=useState(false);
  const signature=provider+"|"+model+"|"+valueText(child.ollama_url);
  const generation=useRef(0);
  useEffect(()=>{generation.current++;setConnection(null);setChecking(false);},[signature]);
  const check=async()=>{
    const id=++generation.current;setChecking(true);
    try{
      const status=await workspace.post<UnknownRecord>("/connection",{
        provider,model,ollama_url:child.ollama_url,num_ctx:child.num_ctx,
        max_output_tokens:child.max_output_tokens,temperature:child.temperature,
        thinking:child.thinking
      });
      if(generation.current===id)setConnection(status);
    }catch(e){if(generation.current===id)notify(e instanceof Error?e.message:"连接检查失败");}
    finally{if(generation.current===id)setChecking(false);}
  };
  const capabilities=asRecord(asRecord(connection?.details).model_capabilities);
  const profile=asRecord(capabilities[model]),reasoning=asRecord(profile.reasoning);
  const levels=Array.isArray(reasoning.levels)?reasoning.levels.filter((x):x is string=>typeof x==="string"):[];
  const off=reasoning.off;
  const thinkingChoices:Array<[string,string]>=[["default","模型默认"]];
  if(reasoning.kind==="toggle"||reasoning.kind==="boolean"){
    thinkingChoices.push(["__on__","开启"],["__off__","关闭"]);
  }else{
    if(off!==undefined&&off!==null)thinkingChoices.push([choiceValue(off),"关闭"]);
    levels.forEach(level=>thinkingChoices.push([level,level]));
  }
  const currentThinking=choiceValue(child.thinking);
  if(!thinkingChoices.some(([x])=>x===currentThinking))thinkingChoices.push([currentThinking,currentThinking+" · 已保存（尚未验证）"]);
  const temperatureSupported=provider!=="chatgpt"&&!(provider==="openai"&&(!profile.id||profile.reasoning))
    &&(!(provider==="anthropic"||provider==="claude_oauth")||asRecord(profile.temperature).supported===true);
  const tasks=Array.isArray(child.task_types)?child.task_types.map(String):[];
  const maxOutput=numberOr(profile.max_output_tokens,32768);
  return <fieldset className="child-model" data-pool-id={String(child.id||index)}>
    <legend>子模型 {index+1} · {valueText(child.label)||String(child.id||"")}</legend>
    <div className="form-grid">
      <label>提供方<select value={provider} onChange={e=>{
        update("provider",e.target.value);
      }}>{poolProviders.map(([v,label])=><option key={v} value={v}>{label}</option>)}</select></label>
      <label>模型 ID<input value={model} onChange={e=>update("model",e.target.value)} placeholder="精确模型 ID"/></label>
      <label>初始能力<select value={numberOr(child.tier,1)} onChange={e=>update("tier",Number(e.target.value))}>
        <option value={1}>基础 · 1</option><option value={2}>较强 · 2</option><option value={3}>很强 · 3</option></select></label>
      <label className="inline-check"><input type="checkbox" checked={child.enabled!==false} onChange={e=>update("enabled",e.target.checked)}/>可参与委派</label>
    </div>
    <div className="button-row"><button type="button" className="subtle-button" disabled={checking||!model.trim()} onClick={()=>void check()}>
      <Link2 size={14}/>{checking?"检查中…":"检查子模型连接"}</button>
      {connection?<span role="status">{connection.ready?"可连接 · 不是生成验收":"不可连接 · 检查凭据及型号"}</span>:null}</div>
    <details className="advanced-settings"><summary>高级配置 <ChevronDown size={15}/></summary>
      <div className="form-grid">
        <label>备注<input maxLength={80} value={valueText(child.label)} onChange={e=>update("label",e.target.value)}/></label>
        <label>子任务步数（1–8）<input type="number" min={1} max={8} value={numberOr(child.max_steps,4)} onChange={e=>update("max_steps",Number(e.target.value))}/></label>
        <label>输出 Token（128–32768）<input type="number" min={128} max={Math.min(32768,maxOutput)} value={numberOr(child.max_output_tokens,2048)} onChange={e=>update("max_output_tokens",Number(e.target.value))}/></label>
        {provider==="ollama"?<>
          <label>本地上下文<input type="number" min={2048} max={262144} value={numberOr(child.num_ctx,8192)} onChange={e=>update("num_ctx",Number(e.target.value))}/></label>
          <label>本地地址<input value={valueText(child.ollama_url)||"http://127.0.0.1:11434"} onChange={e=>update("ollama_url",e.target.value)}/></label>
        </>:null}
        <label>Temperature<input type="number" min={0} max={provider==="anthropic"||provider==="claude_oauth"?1:2} step={0.1}
          value={temperatureSupported?numberOr(child.temperature,0):0} disabled={!temperatureSupported}
          onChange={e=>update("temperature",Number(e.target.value))}/></label>
        <label>Thinking<select value={currentThinking} disabled={!profile.reasoning} onChange={e=>update("thinking",nativeThinking(e.target.value))}>
          {thinkingChoices.map(([v,label])=><option key={v} value={v}>{label}</option>)}</select></label>
      </div>
      <div className="task-kinds"><strong>适用任务（不选择 = 全部）</strong>
        <div className="button-row">{taskKinds.map(([id,label])=><label className="inline-check" key={id}>
          <input type="checkbox" checked={tasks.includes(id)} onChange={e=>update("task_types",e.target.checked?[...tasks,id]:tasks.filter(x=>x!==id))}/>{label}</label>)}</div>
      </div>
      <PricingEditor provider={provider} model={model} value={child.pricing} notify={notify} onChange={x=>update("pricing",x)}/>
    </details>
    <button type="button" className="danger-action" onClick={remove}><Trash2 size={14}/>移除</button>
  </fieldset>;
}

export function ModelPool({pool,setPool,notify}:Props){
  const children=Array.isArray(pool.children)?pool.children.map(asRecord):[];
  const updateChild=(id:string,key:string,value:unknown)=>{
    const next=children.map(c=>String(c.id)===id?{
      ...c,[key]:value,
      ...(key==="provider"||key==="model"?{pricing:null,thinking:null,temperature:0}:{}),
    }:c);
    setPool({...pool,children:next});
  };
  const add=()=>{
    if(children.length>=3)return;
    setPool({...pool,children:[...children,{
      id:"child-"+crypto.randomUUID().slice(0,8),label:"",provider:"ollama",model:"",enabled:true,tier:1,
      task_types:[],max_steps:4,max_output_tokens:2048,num_ctx:8192,ollama_url:"http://127.0.0.1:11434",
      temperature:0,thinking:null,pricing:null
    }]});
  };
  return <div className="panel model-pool-editor">
    <div className="panel-top"><Cpu size={18}/><div><h2>模型池 · Model Pool</h2>
      <p>一个主模型，最多三个子槽位。由模型判断是否委派；子任务只读、单层、预算共享。</p></div></div>
    <div className="button-row">
      <label className="inline-check"><input type="checkbox" checked={pool.enabled!==false} onChange={e=>setPool({...pool,enabled:e.target.checked})}/>启用模型池</label>
      <label className="inline-check"><input type="checkbox" checked={pool.adaptive!==false} onChange={e=>setPool({...pool,adaptive:e.target.checked})}/>使用已审核的同类经验路由</label>
    </div>
    {children.map((child,i)=><ChildEditor key={String(child.id||i)} child={child} index={i}
      update={(k,v)=>updateChild(String(child.id),k,v)}
      remove={()=>setPool({...pool,children:children.filter(c=>c.id!==child.id)})} notify={notify}/>)}
    <button type="button" className="subtle-button" disabled={children.length>=3} onClick={add}><Plus size={15}/>添加子模型（{children.length}/3）</button>
    <p className="subtext">检查连接仅确认目录/认证可访问，不代表真实生成正确。价格是估算来源，不是账单或现金额度。</p>
  </div>;
}
