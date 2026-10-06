// 真实浏览器的前后DOM基准；输入是明确标记的合成投影，不证明Provider速度或模型可靠性。
// 用同一脚本分别拦截基线/当前app.js与CSS；多次交替测量，减少单次GC与主机负载误导。
"use strict";
const {chromium} = require("playwright");
const {execFileSync} = require("node:child_process");
const fs = require("node:fs"), path = require("node:path");
const root=path.resolve(__dirname,"..");
const baseline=process.env.MYTH_UI_BASELINE || "d5e066f";
const base=process.env.MYTH_UI_BASE_URL || "http://127.0.0.1:8773";
const source={before:{},after:{}};
for(const filename of ["app.js","app.css"]){
  source.before[filename]=execFileSync("git",["show",baseline+":src/myth/webui/"+filename],{cwd:root,encoding:"utf8"});
  source.after[filename]=fs.readFileSync(path.join(root,"src/myth/webui",filename),"utf8");
}

// 每个样本使用新页面，完整渲染和相同签名刷新分别度量；强制布局成本包含在完整样本中。
async function sample(browser, version) {
  const page=await browser.newPage({viewport:{width:1440,height:960}});
  await page.route(/\/(app\.js|app\.css)(\?.*)?$/,route=>{
    const name=new URL(route.request().url()).pathname.slice(1);
    return route.fulfill({body:source[version][name],contentType:name.endsWith(".js")?"text/javascript":"text/css"});
  });
  try {
    await page.goto(base,{waitUntil:"networkidle"});
    await page.evaluate(()=>document.fonts.ready);
    return await page.evaluate(()=>{
      const turns=Array.from({length:500},(_,i)=>({run_id:"synthetic-"+i,status:"COMPLETED",current_step:1,activities:[],snapshot:{knowledge:[]},operations:[],reply_timing:{elapsed_seconds:1}}));
      const messages=Array.from({length:1000},(_,i)=>({id:"synthetic-message-"+i,run_id:"synthetic-"+Math.floor(i/2),role:i%2?"assistant":"user",content:i%2?"合成性能数据：保留UNKNOWN、Ticket、Receipt和独立验收。":"合成问题 "+i}));
      const artifacts=Array.from({length:100},(_,i)=>({decision_id:"synthetic-artifact-"+i,run_id:"synthetic-"+(i*5),name:"synthetic/"+i+".md",bytes:128,version:1}));
      const projection={id:"synthetic",messages,turns,artifacts};
      state.threadKey="";
      const start=performance.now(); renderThread(projection);
      // scrollHeight让样本包含真实布局，而非只比较JavaScript向浏览器排队的时间。
      const height=document.querySelector("#thread").scrollHeight;
      const renderMs=performance.now()-start;
      const startRefresh=performance.now();
      for(let i=0;i<50;i++) renderThread(projection);
      return {renderMs,unchangedMeanMs:(performance.now()-startRefresh)/50,domNodes:document.querySelectorAll("#thread *").length,height};
    });
  } finally {await page.close();}
}

// 只输出原始样本与中位数；不对不稳定的机器时延设虚假的CI性能断言。
async function main(){
  const options={headless:true}; if(process.platform==="win32")options.channel="chrome";
  const browser=await chromium.launch(options), samples={before:[],after:[]};
  try {
    for(let i=0;i<7;i++)for(const version of i%2?["after","before"]:["before","after"])samples[version].push(await sample(browser,version));
  } finally {await browser.close();}
  const median=values=>[...values].sort((a,b)=>a-b)[Math.floor(values.length/2)];
  const summary={};
  for(const version of ["before","after"])summary[version]={renderMedianMs:median(samples[version].map(s=>s.renderMs)),unchangedMedianMs:median(samples[version].map(s=>s.unchangedMeanMs)),domNodes:samples[version][0].domNodes};
  if(summary.before.domNodes!==summary.after.domNodes)throw new Error("benchmark content differs");
  const report={baseline,messages:1000,turns:500,artifacts:100,boundary:"synthetic real-DOM projection; not model or provider throughput",samples,summary};
  const output=path.join(root,".work/frontend-performance.json");fs.mkdirSync(path.dirname(output),{recursive:true});fs.writeFileSync(output,JSON.stringify(report,null,2));
  console.log(JSON.stringify(summary));
}
main().catch(error=>{console.error(error.stack);process.exitCode=1;});
