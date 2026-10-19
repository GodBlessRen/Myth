// 两个正式静态入口接入同一真实 Driver：预览期间数据库不能有 Assistant 回答或完成事实。
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
const fixture=JSON.parse(fs.readFileSync(path.resolve(__dirname,'../.work/browser-fixture.json'),'utf8'));
const out=path.resolve(__dirname,'../.work/browser-evidence/streaming');
async function main(){
  fs.mkdirSync(out,{recursive:true});
  const browser=await chromium.launch({headless:true,...(process.platform==='win32'?{channel:'chrome'}:{})});
  const report=[];
  try{
    for(const mode of ['legacy','react']){
      const page=await browser.newPage({viewport:{width:1440,height:960}});
      const errors=[];page.on('pageerror',error=>errors.push(error.message));
      await page.goto(fixture.base+(mode==='react'?'/next/#chat':'/#chat'),{waitUntil:'networkidle'});
      const input=page.locator(mode==='legacy'?'#prompt':'textarea[aria-label="消息输入"]');
      await input.fill('等待反馈：请给出一段完整回答。');
      await page.locator(mode==='legacy'?'#send':'button[aria-label="发送消息"]').click();
      await page.locator('.reply-preview').waitFor({state:'visible',timeout:10000});
      const sid=new URL(page.url()).hash.split('/').at(-1);
      const before=await(await page.request.get(fixture.base+'/api/workspace/sessions/'+sid)).json();
      const turn=before.turns.at(-1);
      assert.equal(turn.status,'RUNNING');
      assert.ok(turn.reply_preview.text);
      assert.equal(before.messages.filter(m=>m.role==='assistant').length,0);
      await page.screenshot({path:path.join(out,mode+'-generating.png')});
      await page.locator(mode==='legacy'?'.message.assistant:not(.reply-preview)':'.message-row.from-myth:not(.reply-preview)').waitFor({state:'visible'});
      const after=await(await page.request.get(fixture.base+'/api/workspace/sessions/'+sid)).json();
      assert.equal(after.turns.at(-1).status,'COMPLETED');
      assert.equal(after.messages.filter(m=>m.role==='assistant').length,1);
      assert.equal(after.turns.at(-1).reply_preview,null);
      assert.deepEqual(errors,[]);
      await page.screenshot({path:path.join(out,mode+'-completed.png')});
      report.push({mode,run_id:turn.run_id,preview_before_commit:true,final_messages:after.messages.length,errors});
      await page.close();
    }
  }finally{await browser.close();}
  fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify(report));
}
main().catch(error=>{console.error(error);process.exitCode=1;});
