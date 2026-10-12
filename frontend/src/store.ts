import {create} from "zustand";

// 纯 UI 偏好，不包含消息/Run/权限/费用，也不写服务端。
type Lens = "overview"|"execution"|"resources";
type UiState = {
  sidebar: boolean; inspector: boolean; theme:"light"|"dark";
  density:"comfortable"|"compact"; lens:Lens; commandOpen:boolean;
  setSidebar:(open:boolean)=>void;setInspector:(open:boolean)=>void;
  toggleTheme:()=>void;toggleDensity:()=>void;setLens:(lens:Lens)=>void;
  setCommandOpen:(open:boolean)=>void;
};
function preference(key:string, fallback:string):string{
  try {return localStorage.getItem("myth-next-"+key)??fallback;} catch{return fallback;}
}
function remember(key:string,value:string){
  try {localStorage.setItem("myth-next-"+key,value);} catch{/* 私密模式可用 */}
}
const prefersDark = typeof window !== "undefined" && matchMedia("(prefers-color-scheme: dark)").matches;
export const useUi = create<UiState>(set=>({
  sidebar:typeof window !== "undefined" && window.innerWidth > 800, inspector:typeof window !== "undefined" && window.innerWidth > 1120,
  theme:preference("theme",prefersDark?"dark":"light") === "dark" ? "dark" : "light",
  density:preference("density","comfortable") === "compact"?"compact":"comfortable",
  lens:"overview",commandOpen:false,
  setSidebar:(sidebar)=>set({sidebar}),
  setInspector:(inspector)=>set({inspector}),
  toggleTheme:()=>set(state=>{const theme=state.theme==="light"?"dark":"light";remember("theme",theme);return {theme};}),
  toggleDensity:()=>set(state=>{const density=state.density==="comfortable"?"compact":"comfortable";remember("density",density);return {density};}),
  setLens:(lens)=>set({lens}),
  setCommandOpen:(commandOpen)=>set({commandOpen}),
}));
