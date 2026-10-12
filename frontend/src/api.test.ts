import {beforeEach,afterEach,expect,it,vi} from "vitest";
import {ApiError,pendingRequestId,clearPending,workspace} from "./api";
import {statusText,displayValue} from "./types";

const saved=new Map<string,string>();
const storage={
  getItem:(key:string)=>saved.get(key)||null,
  setItem:(key:string,value:string)=>{saved.set(key,value);},
  removeItem:(key:string)=>{saved.delete(key);}
};
beforeEach(()=>{
  saved.clear();
  vi.stubGlobal("window",globalThis);
  vi.stubGlobal("sessionStorage",storage);
});
afterEach(()=>vi.unstubAllGlobals());
it("does not infer success or zero for unknown runtime values",()=>{
  expect(statusText("UNKNOWN")).toContain("待核对");
  expect(statusText("COMPLETED")).toBe("已完成");
  expect(displayValue(null)).toBe("N/A");
  expect(displayValue(0)).toBe("0");
});
it("reuses one request ID for one frozen message and changes it for new content",async()=>{
  const a=await pendingRequestId("s-1",["s-1","hello"]);
  const b=await pendingRequestId("s-1",["s-1","hello"]);
  const c=await pendingRequestId("s-1",["s-1","different"]);
  expect(a).toBe(b);expect(a).not.toBe(c);
  clearPending("s-1");expect(saved.has("myth-next-pending-s-1")).toBe(false);
});
it("does not retry an uncertain POST and exposes outcome uncertainty",async()=>{
  const fetch=vi.fn().mockRejectedValue(new TypeError("socket disconnected"));
  vi.stubGlobal("fetch",fetch);
  let observed:unknown;
  try{await workspace.post("/sessions/s-1/messages",{text:"hello",request_id:"id-1"});}
  catch(error){observed=error;}
  expect(observed).toBeInstanceOf(ApiError);
  expect((observed as ApiError).uncertain).toBe(true);
  expect(fetch).toHaveBeenCalledTimes(1);
});
it("GET and command routes preserve server authority",async()=>{
  const fetch=vi.fn().mockResolvedValue({ok:true,json:async()=>({status:"PAUSED"})});
  vi.stubGlobal("fetch",fetch);
  await workspace.control("r-1","pause");
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(fetch.mock.calls[0][0]).toBe("/api/workspace/turns/r-1/pause");
  expect(fetch.mock.calls[0][1].method).toBe("POST");
});
