import {expect,it} from "vitest";
import {clearDraft,draftFor,patchDraft,readDraft,saveDraft,transferDraft} from "./drafts";

it("isolates entire drafts by session identity including docs and Goal",()=>{
  patchDraft("s-1",{text:"first",documentIds:["d-1"],projectId:"p-1",goalId:"g-1"});
  saveDraft("s-2","second");
  expect(readDraft("s-1")).toEqual({text:"first",documentIds:["d-1"],projectId:"p-1",goalId:"g-1"});
  expect(readDraft("s-2").documentIds).toEqual([]);
  const copy=readDraft("s-1");copy.documentIds.push("not-owned");
  expect(readDraft("s-1").documentIds).toEqual(["d-1"]);
  clearDraft("s-1");clearDraft("s-2");
});
it("transfers a complete pending draft to the server-confirmed session",()=>{
  patchDraft("new",{text:"a work request",documentIds:["d-1","d-1"],projectId:"p",goalId:"g"});
  transferDraft("new","s-7");
  expect(readDraft("s-7")).toEqual({text:"a work request",documentIds:["d-1"],projectId:"p",goalId:"g"});
  expect(draftFor("new")).toBe("");
  clearDraft("s-7");
});
