// 会话草稿只保存在当前 Web App 的内存中，不持久化用户正文。
// Run、提交许可与 request_id 不属于本模块；刷新丢失正文是已知的 UX 取舍。
const drafts = new Map<string,string>();
export function draftFor(sessionKey:string):string {return drafts.get(sessionKey)||"";}
export function saveDraft(sessionKey:string,content:string):void {drafts.set(sessionKey,content);}
export function transferDraft(from:string,to:string):void {
  if(from===to)return;
  const content=drafts.get(from);
  if(content!==undefined)drafts.set(to,content);
  drafts.delete(from);
}
export function clearDraft(sessionKey:string):void {drafts.delete(sessionKey);}
