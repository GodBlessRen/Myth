// Chromium Browser Matrix for React replacement. Real local Python HTTP/SQLite fixture,
// no external model/credential access. A successful build alone is not a UI acceptance gate.
import {chromium} from "playwright";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const root=path.resolve(process.cwd(),"..");
const fixture=JSON.parse(fs.readFileSync(path.join(root,".work/browser-fixture.json"),"utf-8"));
const out=path.join(root,".work/react-browser-evidence");
fs.mkdirSync(out,{recursive:true});
const base="http://127.0.0.1:5173/next/";
const widths=[1440,1280,1024,768,390], themes=["light","dark"];
const report={revision:process.env.GITHUB_SHA||"local",fixture:"real Python HTTP/SQLite; fixed Provider",cases:[],errors:[]};
const browser=await chromium.launch({headless:true});
try{
  for(const width of widths)for(const theme of themes){
    const context=await browser.newContext({viewport:{width,height:width>=1024?900:844},colorScheme:theme});
    const page=await context.newPage(),problems=[],writes=[];
    page.on("pageerror",error=>problems.push(error.message));
    page.on("request",request=>{
      if(request.url().includes("/api/")&&request.method()!=="GET")writes.push(request.method()+" "+request.url());
    });
    const current={width,theme,status:"RUNNING",states:[]};
    try{
      await page.goto(base,{waitUntil:"domcontentloaded"});
      await page.locator(".chat-welcome h1").waitFor({state:"visible",timeout:20000});
      assert.match(await page.locator(".chat-welcome h1").innerText(),/开始一段工作/);
      const initial=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>innerWidth+1,
        bg:getComputedStyle(document.body).backgroundColor,theme:document.documentElement.dataset.theme}));
      assert.equal(initial.overflow,false,"home horizontal overflow");
      assert.equal(initial.theme,theme,"initial theme mismatch");
      await page.screenshot({path:path.join(out,`${width}-${theme}-home.png`)});
      current.states.push("home");

      // A completed conversation exercises Markdown, tool facts, metadata and third-column navigation.
      await page.goto(base+"#chat/"+encodeURIComponent(fixture.ids.completed));
      await page.locator(".message-row").first().waitFor({state:"visible",timeout:20000});
      assert.equal(await page.locator(".conversation").count(),1);
      assert.equal(await page.locator(".message-row.from-user").count()>0,true);
      if(width<=1120){
        await page.locator(".inspector-control").click();
      }
      await page.locator(".obs-tabs [role=tab]").first().waitFor({state:"visible"});
      await page.locator('.obs-tabs [role=tab]').nth(1).click();
      await page.locator('.obs-scroll[role="tabpanel"]').waitFor({state:"visible"});
      assert.equal(await page.locator('.obs-tabs [aria-selected="true"]').count(),1);
      await page.screenshot({path:path.join(out,`${width}-${theme}-completed.png`)});
      current.states.push("completed");

      // UNKNOWN stays explicit; opening the app must not automatically issue control commands.
      await page.goto(base+"#chat/"+encodeURIComponent(fixture.ids.unknown));
      await page.locator(".message-row").first().waitFor({state:"visible",timeout:20000});
      await page.getByText("UNKNOWN · 待核对").first().waitFor({state:"visible",timeout:10000});
      await page.screenshot({path:path.join(out,`${width}-${theme}-unknown.png`)});
      current.states.push("UNKNOWN");
      assert.deepEqual(writes,[],"Passive navigation posted an unsafe command");
      assert.deepEqual(problems,[],"Browser JavaScript exceptions");
      const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);
      assert.equal(overflow,false,"unknown view horizontal overflow");
      current.status="PASS";
    }catch(error){
      current.status="FAIL";
      report.errors.push({width,theme,message:String(error)});
      try{await page.screenshot({path:path.join(out,`failure-${width}-${theme}.png`)});}catch{/* page may be closed */}
      console.error("FAIL",width,theme,error);
    }finally{report.cases.push(current);await context.close();}
    console.log(width,theme,current.status,current.states.join(","));
  }
}finally{await browser.close();}
fs.writeFileSync(path.join(out,"results.json"),JSON.stringify(report,null,2));
console.log(JSON.stringify({cases:report.cases.length,errors:report.errors.length}));
if(report.errors.length)process.exitCode=1;
