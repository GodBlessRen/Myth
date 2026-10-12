import type {Bootstrap, Session, Settings, UnknownRecord} from "./types";

export class ApiError extends Error {
  constructor(message: string, public readonly status: number | null, public readonly uncertain: boolean) {
    super(message); this.name = "ApiError";
  }
}
export type Method = "GET" | "POST";

// 写入永不隐式重试；网络中断后的 POST 可能已经提交，必须先读取权威快照再决定。
async function json<T>(url: string, method: Method, payload?: unknown, signal?: AbortSignal): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 20_000);
  const abort = () => controller.abort();
  signal?.addEventListener("abort", abort);
  try {
    const response = await fetch(url, {
      method,
      headers: method === "POST" ? {"Content-Type":"application/json"} : undefined,
      body: method === "POST" ? JSON.stringify(payload ?? {}) : undefined,
      signal: controller.signal,
      credentials: "same-origin",
      cache: "no-store",
    });
    const body: unknown = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = body && typeof body === "object" && "error" in body ? (body as {error:unknown}).error : undefined;
      throw new ApiError(typeof error === "string" ? error : "HTTP " + response.status, response.status, false);
    }
    return body as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(method === "POST"
      ? "连接中断，请先核对会话状态。提交可能已经生效，不能直接重新创建相同任务。"
      : "工作区读取失败，已保留最后一次成功的快照。", null, method === "POST");
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener("abort", abort);
  }
}
export const workspace = {
  read<T>(path: string, signal?: AbortSignal) {
    return json<T>("/api/workspace" + path, "GET", undefined, signal);
  },
  post<T>(path: string, value: unknown) {
    return json<T>("/api/workspace" + path, "POST", value);
  },
  bootstrap(signal?: AbortSignal) {return this.read<Bootstrap>("", signal);},
  session(id: string, signal?: AbortSignal) {return this.read<Session>("/sessions/" + encodeURIComponent(id), signal);},
  settings(input: Settings) {return this.post<Settings>("/settings", input);},
  control(run: string, action: "pause"|"resume"|"stop"|"continue"|"steer"|"compact"|"switch_model"|"switch_thinking"|"answer", value: UnknownRecord = {}) {
    return this.post<UnknownRecord>("/turns/" + encodeURIComponent(run) + "/" + action, value);
  },
};
export const auth = {
  read<T>(provider: "chatgpt"|"claude"|"providers", path = "") {
    return json<T>("/api/auth/"+provider+path, "GET");
  },
  post<T>(provider: "chatgpt"|"claude"|"providers", path: string, value: unknown) {
    return json<T>("/api/auth/"+provider+path, "POST", value);
  },
};

// 只存哈希与请求 ID，不把用户正文写入 storage；刷新/超时后同意图仍用相同身份。
export async function pendingRequestId(sessionId: string, payload: unknown): Promise<string> {
  const data = new TextEncoder().encode(JSON.stringify(payload));
  const hash = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", data)), b=>b.toString(16).padStart(2,"0")).join("");
  const key = "myth-next-pending-" + sessionId;
  try {
    const old = JSON.parse(sessionStorage.getItem(key) || "null") as {hash:string;id:string}|null;
    if (old?.hash === hash && old.id) return old.id;
  } catch {/* 失效浏览器偏好不能阻碍业务 */}
  const id = crypto.randomUUID();
  try {sessionStorage.setItem(key, JSON.stringify({hash,id}));} catch {/* 降级成单次身份；失败提示不自动重发 */}
  return id;
}
export function clearPending(sessionId: string) {
  try {sessionStorage.removeItem("myth-next-pending-"+sessionId);} catch {/* 限制浏览器存储时忽略 */}
}
