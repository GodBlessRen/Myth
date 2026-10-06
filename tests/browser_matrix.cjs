// 生产字节身份 + Chromium 状态矩阵；固定 Provider 不能证明真实模型能力。
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {chromium}=require('playwright'),{verifyAuditProbes}=require('./browser_audit_probes.cjs');
const root=path.resolve(__dirname,'..'),fixture=JSON.parse(fs.readFileSync(path.join(root,'.work/browser-fixture.json')));
const baseline=process.argv.includes('--baseline'),smoke=process.argv.includes('--smoke');
const executable=process.argv.includes('--browser-executable')?process.argv[process.argv.indexOf('--browser-executable')+1]:undefined;
const out=path.join(root,'.work/browser-evidence');fs.mkdirSync(out,{recursive:true});
const source=fs.readFileSync(path.join(__dirname,'browser_accessibility.cjs'),'utf8');
const report={boundary:fixture.boundary,fixturePid:fixture.pid,baseline,assetIdentity:[],cases:[],errors:[]};
const scenarios=[['home',fixture.empty+'/#chat'],['chat',fixture.base+'/#chat/'+fixture.ids.completed],
  ['execution',fixture.base+'/#chat/'+fixture.ids.completed,'execution'],['waiting',fixture.base+'/#chat/'+fixture.ids.waiting],
  ['recovery',fixture.base+'/#chat/'+fixture.ids.unknown,'execution'],['settings',fixture.base+'/#settings'],['model-pool',fixture.base+'/#settings','pool'],
  ['statistics',fixture.base+'/#chat/'+fixture.ids.completed,'overview'],['empty',fixture.empty+'/#projects'],['error',fixture.base+'/#chat/'+fixture.ids.failed],
  ['focus',fixture.base+'/#chat/'+fixture.ids.completed,'focus'],['drawer',fixture.base+'/#chat/'+fixture.ids.interrupted,'resources'],['running',fixture.base+'/#chat','running']];
async function main(){
  const launch={headless:true};if(executable)launch.executablePath=executable;else if(process.platform==='win32')launch.channel='chrome';
  const browser=await chromium.launch(launch);
  try{
    report.auditProbes=await verifyAuditProbes(browser);
    const probe=await browser.newContext();
    try{
      for(const[url,asset]of Object.entries(fixture.assets)){
        const response=await probe.request.get(fixture.base+url),body=await response.body();
        const expected=fs.readFileSync(path.join(root,'src/myth/webui',asset.file));
        const digest=value=>crypto.createHash('sha256').update(value).digest('hex');
        assert.equal(response.status(),200,url);assert.deepEqual(body,expected,'served source differs: '+url);
        assert.equal(digest(body),asset.sha256,'fixture began with different source: '+url);assert.equal(response.headers()['content-type'],asset.mime,'MIME: '+url);
        report.assetIdentity.push({url,sha256:digest(body),bytes:body.length});
      }
      for(const url of ['/taiji.svg','/ink-taiji.png','/myth-mark.svg','/myth-mark-dark.svg'])assert.equal((await probe.request.get(fixture.base+url)).status(),404,url);
    }finally{await probe.close();}
    for(const width of baseline?[1440]:smoke?[390]:[1440,1280,1024,768,390])for(const theme of ['light','dark']){
      for(const[name,url,action]of scenarios){
        const context=await browser.newContext({viewport:{width,height:width>=1024?960:844},colorScheme:theme}),page=await context.newPage(),errors=[],external=[];
        page.setDefaultTimeout(12000);page.on('pageerror',error=>errors.push(error.message));page.on('console',message=>{if(message.type()==='error')errors.push(message.text());});
        page.on('request',request=>{if(!['127.0.0.1','localhost'].includes(new URL(request.url()).hostname))external.push(request.url());});
        const entry={state:name,width,theme,source:'production HTTP/static assets'};
        try{
          await page.goto(url,{waitUntil:'networkidle'});await page.evaluate(()=>document.fonts.ready);await page.waitForTimeout(350);
          if(['overview','execution','resources'].includes(action)){if(width<=1120)await page.locator('#inspectorToggle').click();await page.locator(`[data-inspector-lens="${action}"]`).click();}
          else if(action==='focus'&&width>1120)await page.locator('#focusMode').click();
          else if(action==='pool'){await page.locator('#poolAdd').click();await page.locator('#poolChildren').scrollIntoViewIfNeeded();}
          else if(action==='running'){await page.locator('#prompt').fill('等待反馈：核对当前执行状态。');await page.locator('#send').click();await page.locator('.typing .brand-wait').waitFor({state:'visible'});}
          await page.waitForTimeout(action==='running'?0:300);
          const run=await page.evaluate(()=>state.session?.turns.at(-1));
          const expectedStatus={chat:'COMPLETED',execution:'COMPLETED',statistics:'COMPLETED',focus:'COMPLETED',waiting:'WAITING_USER',recovery:'UNKNOWN',error:'FAILED',drawer:'INTERRUPTED',running:'RUNNING'}[name];
          if(expectedStatus)assert.equal(run?.status,expectedStatus,name+' intended Runtime state');entry.run_id=run?.run_id;entry.run_status=run?.status;
          if(name==='recovery')assert.equal(await page.locator('#turnNotice').evaluate(node=>node.classList.contains('warning')),true);
          if(name==='drawer'&&width<=1120)assert.equal(await page.locator('#runtimeInspector').getAttribute('aria-modal'),'true');
          if(name==='model-pool')assert.ok(await page.locator('#poolChildren .pool-child').count());
          const filename=`${width}-${theme}-${name}.png`;await page.screenshot({path:path.join(out,filename),fullPage:true});entry.screenshot=filename;
          Object.assign(entry,await page.evaluate(()=>({scrollWidth:document.documentElement.scrollWidth,viewport:innerWidth,background:getComputedStyle(document.body).backgroundColor,
            fonts:[...document.fonts].map(f=>({family:f.family,status:f.status})),imageFailures:[...document.images].filter(i=>!i.complete||!i.naturalWidth).map(i=>i.getAttribute('src')),
            bodyFont:getComputedStyle(document.body).fontSize,textWeight:getComputedStyle(document.querySelector('.message-content')||document.body).fontWeight})));
          entry.accessibility=await page.evaluate(source+'\nauditSurface()');
          assert.ok(entry.scrollWidth<=width+1,'horizontal overflow');assert.deepEqual(entry.imageFailures,[]);assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
          assert.ok(entry.fonts.filter(font=>['"Myth Sans"','"Myth Serif"','"Myth Latin"'].includes(font.family)).every(font=>font.status==='loaded'),'offline fonts');
          assert.equal(entry.background,theme==='light'?'rgb(255, 254, 248)':'rgb(14, 16, 15)');
          if(!baseline)for(const key of ['contrast_failures','weight_failures','target_failures','boundary_failures','icon_failures','unmeasured'])assert.deepEqual(entry.accessibility[key],[],key);
          entry.status='PASS';
        }catch(error){entry.status='FAIL';entry.error=error.message;report.errors.push({case:`${width}/${theme}/${name}`,error:error.message});console.error('FAIL',width,theme,name,error.message);try{await page.screenshot({path:path.join(out,`failure-${width}-${theme}-${name}.png`)});}catch{}}
        finally{report.cases.push(entry);await context.close();}
      }console.log('Finished',width,theme,report.cases.length);
    }
  }finally{await browser.close();fs.writeFileSync(path.join(out,smoke?'smoke.json':'matrix.json'),JSON.stringify(report,null,2));}
  console.log(JSON.stringify({cases:report.cases.length,failures:report.errors.length,assets:report.assetIdentity.length}));if(report.errors.length)process.exitCode=1;
}
main().catch(error=>{console.error(error.stack);process.exitCode=1;});
