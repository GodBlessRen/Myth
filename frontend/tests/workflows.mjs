// 独立的真实 HTTP/SQLite 浏览器工作流验收，所有写入仅发生在固定夹具临时目录。
// Cross-route draft preservation, actual upload and idempotent send are judged through public UI/HTTP only.
import {chromium} from "playwright";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const root=path.resolve(process.cwd(),"..");
const fixture=JSON.parse(fs.readFileSync(path.join(root,".work/browser-fixture.json"),"utf8"));
const base=process.env.MYTH_FRONTEND_URL||"http://127.0.0.1:5173/next/";
const mode=process.env.MYTH_FRONTEND_MODE||"dev";
const browser=await chromium.launch({headless:true,channel:process.env.MYTH_BROWSER_CHANNEL||undefined});
const facts={mode,states:[],serverSession:null,errors:[]};
try{
  const context=await browser.newContext({viewport:{width:1440,height:900}});
  const page=await context.newPage();
  page.setDefaultTimeout(20000);
  const http=(suffix)=>new URL("/api/workspace"+suffix,base).href;
  const fresh=async()=>{await page.goto(base+"#chat",{waitUntil:"domcontentloaded"});
    await page.locator('textarea[aria-label="消息输入"]').waitFor({state:"visible"});};
  await fresh();
  const input=page.locator('textarea[aria-label="消息输入"]');
  await input.fill("跨页暂存的正文，不应被发送");
  await page.getByRole("combobox",{name:"关联项目"}).selectOption(fixture.ids.project);
  await page.getByRole("combobox",{name:"长期 Goal"}).selectOption(fixture.ids.goal);
  await page.getByRole("button",{name:"添加知识资料"}).click();
  const check=page.locator(".attachment-popover input[type=checkbox]").first();
  await check.check();
  assert.equal(await page.locator(".attachment-strip button").count(),1,"one document attached");
  await page.goto(base+"#goals",{waitUntil:"domcontentloaded"});
  await page.getByRole("heading",{name:"目标与计划"}).waitFor({state:"visible"});
  await fresh();
  assert.equal(await input.inputValue(),"跨页暂存的正文，不应被发送");
  assert.equal(await page.getByRole("combobox",{name:"关联项目"}).inputValue(),fixture.ids.project);
  assert.equal(await page.getByRole("combobox",{name:"长期 Goal"}).inputValue(),fixture.ids.goal);
  assert.equal(await page.locator(".attachment-strip button").count(),1);
  facts.states.push("full-draft-cross-route");

  // Explicit new chat clears only the empty-session draft, unlike ordinary navigation.
  await page.locator(".new-conversation").click();
  assert.equal(await input.inputValue(),"");
  assert.equal(await page.locator(".attachment-strip button").count(),0);
  facts.states.push("explicit-new-chat");

  // A user-selected UTF-8 text file is safely imported through the actual Python API.
  await page.getByRole("button",{name:"添加知识资料"}).click();
  await page.locator('input[aria-label="本地文本文件"]').setInputFiles({
    name:"react-contract.md",mimeType:"text/markdown",
    buffer:Buffer.from("# React 19 验收\n附件必须由 Python Knowledge 负责持久化。","utf8"),
  });
  await page.getByRole("button",{name:/选择本地 UTF-8 文本/}).waitFor({state:"visible",timeout:30000}).catch(()=>{});
  await page.locator(".attachment-strip button").first().waitFor({state:"visible",timeout:30000});
  facts.states.push("file-import-as-durable-document");

  await input.fill("请解释本轮 React 迁移并给出一个回答。");
  await input.press("Enter");
  await page.waitForURL(url=>url.hash.startsWith("#chat/")&&url.hash.length>12,{timeout:30000});
  const sid=decodeURIComponent(new URL(page.url()).hash.slice("#chat/".length));
  facts.serverSession=sid;
  await page.locator(".message-row.from-user").waitFor({state:"visible",timeout:30000});
  const resp=await page.request.get(http("/sessions/"+encodeURIComponent(sid)));
  assert.equal(resp.status(),200);
  const snapshot=await resp.json();
  assert.equal(snapshot.turns.length,1,"one user submission admits exactly one Run");
  assert.equal(snapshot.messages.filter(msg=>msg.role==="user").length,1,"one persisted user message");
  assert.ok(snapshot.messages[0].content.includes("[doc:"),"attached document provenance remains in message");
  facts.states.push("one-turn-and-cited-document");
  await page.reload({waitUntil:"domcontentloaded"});
  await page.locator(".message-row.from-user").waitFor({state:"visible"});
  assert.equal(await page.locator(".message-row.from-user").count(),1,"refresh cannot repeat side effect");
  facts.states.push("reload-read-only");

  // Route a project file to a draft, not to an unauthorized browser-side filesystem read.
  await page.goto(base+"#projects/"+encodeURIComponent(fixture.ids.project));
  await page.getByRole("heading",{name:"本地文件"}).waitFor({state:"visible"});
  await page.getByRole("button",{name:/README.md/}).click();
  await page.waitForURL(url=>url.hash==="#chat");
  await page.locator('textarea[aria-label="消息输入"]').waitFor({state:"visible"});
  assert.match(await page.locator('textarea[aria-label="消息输入"]').inputValue(),/请读取项目文件.*README.md/);
  facts.states.push("project-file-only-prepares-draft");
  await context.close();
}catch(error){
  facts.errors.push(String(error));
  console.error(error);
}finally{await browser.close();}
const out=path.join(root,".work/react-browser-evidence",mode);
fs.mkdirSync(out,{recursive:true});
fs.writeFileSync(path.join(out,"workflows.json"),JSON.stringify(facts,null,2));
console.log(JSON.stringify({mode,states:facts.states,errors:facts.errors}));
if(facts.errors.length)process.exitCode=1;
