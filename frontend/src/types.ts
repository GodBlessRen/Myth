// 只描述经 Python 公开门面投影的字段；未测量的值不推断为 0。
export type UnknownRecord = Record<string, unknown>;
export type RunStatus = "RUNNING" | "WAITING_USER" | "PAUSED" | "INTERRUPTED" | "UNKNOWN" | "RECOVERING"
  | "RECOVERY_REQUIRED" | "COMPLETED" | "FAILED" | "CANCELLED" | "BUDGET_EXHAUSTED" | string;
export type Message = {
  id: string; role: "user" | "assistant" | "tool" | string;
  content: string; run_id?: string | null;
  metadata?: { reply_elapsed_seconds?: number | null; [key: string]: unknown };
};
export type Control = {
  revision?: number; paused?: boolean; stopped?: boolean;
  model?: string; thinking?: string | null; steering_note?: string; [key: string]: unknown;
};
export type Turn = {
  run_id: string; status: RunStatus; question_id?: string | null;
  driver_active?: boolean; current_step?: number; max_steps?: number;
  error?: string; control?: Control; settings?: Settings;
  activities?: UnknownRecord[]; operations?: UnknownRecord[]; events?: UnknownRecord[];
  execution_graph?: unknown; model_usage?: UnknownRecord; provider_evidence?: UnknownRecord;
  information_control?: UnknownRecord; delivery?: UnknownRecord; sota_route?: UnknownRecord;
  liveness?: UnknownRecord; execution_cursor?: UnknownRecord; reply_timing?: UnknownRecord;
  reply_preview?: {text:string;state:"generating"} | null;
  snapshot?: {goal?: {goal_id?: string}; knowledge?: Array<{document_id:string;title:string}>};
  goal_current?: Goal | null;
};
export type Artifact = {decision_id: string; run_id?: string; title?: string; name?: string; [key: string]: unknown};
export type Session = {id: string;title: string;project_id?: string | null; pinned?: boolean; archived?: boolean;
  updated_at?: string; messages: Message[]; turns: Turn[]; artifacts: Artifact[]; statistics?: UnknownRecord};
export type SessionListItem = Pick<Session, "id" | "title" | "project_id" | "pinned" | "archived" | "updated_at">;
export type Project = {id:string;name:string;description?:string;root?:string|null;instructions?:string;[key:string]:unknown};
export type Document = {id:string;title:string;project_id?:string|null;archived?:boolean;content?:string;[key:string]:unknown};
export type Goal = {goal_id:string;title:string;description?:string;state?:string;work?:UnknownRecord;[key:string]:unknown};
export type Settings = {provider:string;model:string;ollama_url?:string;max_steps?:number;max_output_tokens?:number;
  num_ctx?:number;temperature?:number;thinking?:string|boolean|null;model_pool?:UnknownRecord;[key:string]:unknown};
export type Bootstrap = {projects:Project[];sessions:SessionListItem[];settings:Settings;documents:Document[];
  goals:Goal[];platform?:UnknownRecord;executor?:UnknownRecord;recoverable_runs?:unknown[];[key:string]:unknown};
export const finalStatus = new Set(["COMPLETED","FAILED","CANCELLED","BUDGET_EXHAUSTED"]);
export const activeStatus = new Set(["RUNNING","WAITING_USER","PAUSED","INTERRUPTED","UNKNOWN","RECOVERING","RECOVERY_REQUIRED"]);
export const statusText = (status?: string) => ({
  RUNNING: "运行中",WAITING_USER:"等待回复",PAUSED:"已暂停",INTERRUPTED:"已中断",
  UNKNOWN:"UNKNOWN · 待核对",RECOVERING:"恢复中",RECOVERY_REQUIRED:"需要恢复",
  COMPLETED:"已完成",FAILED:"执行失败",CANCELLED:"已取消",BUDGET_EXHAUSTED:"预算用尽"
} as Record<string,string>)[status||""] || status || "空闲";
export const asRecord = (value: unknown): UnknownRecord =>
  value !== null && typeof value === "object" && !Array.isArray(value) ? value as UnknownRecord : {};
export const displayValue = (value: unknown): string =>
  value == null ? "N/A" : typeof value === "string" ? value : typeof value === "number"
    ? Number.isFinite(value) ? value.toLocaleString("zh-CN") : "N/A"
    : typeof value === "boolean" ? (value ? "是" : "否") : JSON.stringify(value);
