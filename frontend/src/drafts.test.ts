import {expect,it} from "vitest";
import {clearDraft,draftFor,saveDraft,transferDraft} from "./drafts";

it("scopes drafts by conversation identity",()=>{
  saveDraft("s-1","first");saveDraft("s-2","second");
  expect(draftFor("s-1")).toBe("first");
  expect(draftFor("s-2")).toBe("second");
  clearDraft("s-1");clearDraft("s-2");
});
it("transfers an unsubmitted draft to the server confirmed session",()=>{
  saveDraft("new","the message");
  transferDraft("new","s-7");
  expect(draftFor("s-7")).toBe("the message");
  expect(draftFor("new")).toBe("");
  clearDraft("s-7");
});
