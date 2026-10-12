// 草稿仅保存在浏览器内存，不写 Runtime、LocalStorage 或日志。
// 同一 Session 的正文、资料和用户意图共享身份；页面切换不丢部分字段。
export type ChatDraft={text:string;documentIds:string[];projectId:string;goalId:string};
const EMPTY:ChatDraft={text:"",documentIds:[],projectId:"",goalId:""};
const drafts=new Map<string,ChatDraft>();
export function readDraft(identity:string):ChatDraft {
  const value=drafts.get(identity)||EMPTY;
  return {...value,documentIds:[...value.documentIds]};
}
export function patchDraft(identity:string,patch:Partial<ChatDraft>):ChatDraft {
  const updated={...readDraft(identity),...patch};
  updated.documentIds=[...new Set(updated.documentIds)];
  drafts.set(identity,updated);return readDraft(identity);
}
export function draftFor(identity:string):string {return readDraft(identity).text;}
export function saveDraft(identity:string,text:string):void {patchDraft(identity,{text});}
export function transferDraft(from:string,to:string):void {
  if(from===to)return;
  if(drafts.has(from))drafts.set(to,readDraft(from));
  drafts.delete(from);
}
export function clearDraft(identity:string):void {drafts.delete(identity);}
